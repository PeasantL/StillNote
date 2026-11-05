"""WebKit layout checks. The viewport shim models a keyboard, not native iPadOS."""

from threading import Thread

import pytest
from werkzeug.serving import make_server

from app import create_app

playwright_api = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def live_app(tmp_path_factory):
    app = create_app({"DATABASE": str(tmp_path_factory.mktemp("layout") / "notes.db")})
    with app.test_client() as client:
        note = client.post("/api/notes", json={"title": "Landscape keyboard check"}).get_json()
        client.patch(f"/api/notes/{note['id']}", json={
            "content": "\n".join(f"Line {i}: keep the writing readable." for i in range(100)),
            "tags": ["ideas", "personal"],
        })
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join()
    server.server_close()


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as playwright:
        browser = playwright.webkit.launch()
        yield browser
        browser.close()


@pytest.fixture()
def page(browser, live_app):
    context = browser.new_context(
        viewport={"width": 1210, "height": 834},
        screen={"width": 1210, "height": 834},
        device_scale_factor=2, is_mobile=True, has_touch=True,
    )
    # A keyboard can change these values while innerHeight/CSS vh stay unchanged.
    context.add_init_script("""(() => {
      const viewport = new EventTarget();
      Object.assign(viewport, { height: 834, offsetTop: 0, scale: 1 });
      Object.defineProperty(window, 'visualViewport', { value: viewport });
      window.setTestViewport = (height, offsetTop = 0, scale = 1, event = 'resize') => {
        Object.assign(viewport, { height, offsetTop, scale });
        viewport.dispatchEvent(new Event(event));
      };
    })();""")
    page = context.new_page()
    page.goto(live_app)
    page.wait_for_selector(".sn-ready")
    page.wait_for_selector("#editor:not(.d-none)")
    yield page
    context.close()


def set_viewport(page, height, offset=0, event="resize"):
    page.evaluate("([h, y, event]) => setTestViewport(h, y, 1, event)", [height, offset, event])
    page.wait_for_function(
        """([height, offset]) => document.querySelector('.app-shell').offsetHeight === height
          && document.documentElement.style.getPropertyValue('--sn-viewport-top') === `${offset}px`""",
        arg=[height, offset],
    )


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_landscape_keyboard_keeps_editor_readable(page, theme):
    page.evaluate("theme => applyTheme(theme)", theme)
    page.locator("#noteContent").focus()
    for height, offset in [(460, 0), (380, 80), (320, 160)]:
        set_viewport(page, height, offset)
        metrics = page.evaluate("""() => {
          const rect = selector => document.querySelector(selector).getBoundingClientRect();
          const shell = rect('.app-shell');
          const content = rect('#noteContent');
          const title = rect('#noteTitle');
          return {
            shellTop: shell.top + scrollY, shellBottom: shell.bottom + scrollY,
            contentTop: content.top + scrollY, contentBottom: content.bottom + scrollY,
            contentHeight: content.height, titleHeight: title.height,
            fontSize: parseFloat(getComputedStyle(document.querySelector('#noteContent')).fontSize),
            overflow: document.documentElement.scrollWidth > innerWidth,
            active: document.activeElement.id,
          };
        }""")
        assert abs(metrics["shellTop"] - offset) <= 1
        assert metrics["shellBottom"] <= height + offset + 1
        assert metrics["contentHeight"] >= 128
        assert metrics["titleHeight"] >= 27
        assert metrics["fontSize"] >= 16
        assert metrics["contentTop"] >= offset
        assert metrics["contentBottom"] <= height + offset + 1
        assert not metrics["overflow"]
        assert metrics["active"] == "noteContent"
        assert page.locator("#tagList").evaluate("el => el.scrollWidth <= el.clientWidth")

    # Editing at the end of a long note must still save while the keyboard is up.
    page.locator("#noteContent").press("ControlOrMeta+End")
    page.locator("#noteContent").press("End")
    page.locator("#noteContent").press("Enter")
    page.locator("#noteContent").press_sequentially("Still readable with the keyboard open.")
    page.wait_for_function("document.querySelector('#saveStatus').textContent === 'Saved'")
    saved = page.request.get(page.url + "api/notes").json()[0]
    assert "Still readable with the keyboard open." in saved["content"]
    assert page.locator("#noteContent").evaluate("el => el.scrollTop > 0")

    set_viewport(page, 834)
    assert page.locator("#noteContent").bounding_box()["height"] > 500
    assert not page.locator("html").evaluate("el => el.classList.contains('sn-compact-viewport')")


def test_tag_editor_scrolls_in_short_landscape_viewport(page):
    set_viewport(page, 300)
    page.locator("#editTags").click()
    page.locator("#noteTags").fill(", ".join(f"long tag number {i}" for i in range(20)))
    assert page.locator("#noteTags").evaluate("el => el === document.activeElement")
    assert page.locator("#noteContent").bounding_box()["height"] >= 128
    assert page.locator(".writing-area").evaluate("el => el.scrollHeight > el.clientHeight")
    # Both fields remain reachable even when all twenty tags wrap onto many rows.
    page.locator("#noteContent").scroll_into_view_if_needed()
    content = page.locator("#noteContent").bounding_box()
    assert content["y"] >= 52
    assert content["y"] + content["height"] <= 300
    page.locator("#noteContent").fill("Still reachable below the tags.")
    page.locator("#doneTags").click()
    assert page.locator("#tagEditor").is_hidden()


def test_visual_viewport_pan_and_pinch_zoom(page):
    set_viewport(page, 380)
    set_viewport(page, 380, 120, "scroll")
    assert page.locator(".app-shell").evaluate("el => el.getBoundingClientRect().top + scrollY") == 120
    page.evaluate("setTestViewport(190, 240, 2)")
    page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
    assert page.locator(".app-shell").evaluate("el => el.offsetHeight") == 380
    assert page.locator("html").evaluate("el => el.style.getPropertyValue('--sn-viewport-top')") == "120px"
    set_viewport(page, 834)


@pytest.mark.parametrize("width,height,touch", [(1440, 900, False), (600, 834, True)])
def test_desktop_and_narrow_window_remain_usable(browser, live_app, width, height, touch):
    context = browser.new_context(viewport={"width": width, "height": height}, has_touch=touch)
    try:
        page = context.new_page()
        # Exercise the innerHeight fallback for browsers without VisualViewport.
        page.add_init_script("Object.defineProperty(window, 'visualViewport', { value: undefined })")
        page.goto(live_app)
        page.wait_for_selector(".sn-ready")
        page.wait_for_selector("#editor:not(.d-none)")
        assert page.locator("#noteContent").bounding_box()["height"] >= 128
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        if width < 768:
            page.locator("#backToList").click()
            assert page.locator(".note-browser").is_visible()
            page.locator("#openSidebar").click()
            page.wait_for_function("document.querySelector('.sidebar').getBoundingClientRect().x >= 0")
            assert page.locator(".sidebar").bounding_box()["x"] >= 0
            page.locator("#closeSidebar").click()
            assert not page.locator("body").evaluate("el => el.classList.contains('sidebar-open')")
    finally:
        context.close()
