"""Behavioural WebKit checks against synthetic notes and temporary databases."""
from threading import Thread

import pytest
from werkzeug.serving import make_server

from app import create_app

playwright_api = pytest.importorskip('playwright.sync_api')


@pytest.fixture(scope='module')
def browser():
    with playwright_api.sync_playwright() as playwright:
        browser = playwright.webkit.launch()
        yield browser
        browser.close()


@pytest.fixture()
def editor(browser, tmp_path):
    app = create_app({'TESTING': True, 'DATABASE': str(tmp_path / 'notes.db')})
    client = app.test_client()
    first = client.post('/api/notes', json={'title': 'First', 'content': 'First body'}).get_json()
    second = client.post('/api/notes', json={'title': 'Second', 'content': 'Second body'}).get_json()
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    context = browser.new_context(viewport={'width': 1280, 'height': 900})
    page = context.new_page()
    page.goto(f'http://127.0.0.1:{server.server_port}')
    page.wait_for_selector('.sn-ready')
    page.locator(f'[data-id="{first["id"]}"]').click()
    page.wait_for_function("document.querySelector('#noteTitle').value === 'First'")
    yield page, client, first, second
    context.close()
    server.shutdown()
    thread.join()
    server.server_close()


def test_switch_flushes_pending_edits(editor):
    page, client, first, second = editor
    page.locator('#noteContent').fill('Must survive immediate switch')
    page.locator(f'[data-id="{second["id"]}"]').click()
    page.wait_for_function("document.querySelector('#noteTitle').value === 'Second'")
    assert client.get(f'/api/notes/{first["id"]}').get_json()['content'] == 'Must survive immediate switch'
    assert page.locator('#noteContent').input_value() == 'Second body'


def test_typing_during_save_is_serialized_without_library_reload(editor):
    page, client, first, _ = editor
    held = []
    requests = []
    page.on('request', lambda request: requests.append(request.url))

    def delay_first(route):
        if route.request.method == 'PATCH' and not held:
            held.append((route, route.fetch()))
        else:
            route.continue_()

    page.route('**/api/notes/*', delay_first)
    page.locator('#noteContent').fill('Earlier text')
    page.locator('#saveNow').click()
    page.wait_for_function('state.saving !== null')
    page.locator('#noteContent').fill('Newer text during save')
    route, response = held[0]
    route.fulfill(response=response)
    page.wait_for_function("document.querySelector('#saveStatus').textContent === 'Saved'")
    assert client.get(f'/api/notes/{first["id"]}').get_json()['content'] == 'Newer text during save'
    assert not any('/api/notes?' in url or '/api/tags' in url for url in requests)
    assert page.evaluate("localStorage.getItem('stillnote-draft-' + state.selected.id)") is None


def test_failed_save_blocks_switch_and_recovers_after_reload(editor):
    page, client, first, second = editor
    def fail_save(route):
        if route.request.method == 'PATCH':
            route.fulfill(status=503, content_type='application/json', body='{"error":"Unavailable"}')
        else:
            route.continue_()
    page.route('**/api/notes/*', fail_save)
    page.locator('#noteContent').fill('Recover this pending draft')
    page.locator(f'[data-id="{second["id"]}"]').click()
    page.wait_for_function("document.querySelector('#saveStatus').textContent.startsWith('Save failed')")
    assert page.locator('#noteTitle').input_value() == 'First'
    assert client.get(f'/api/notes/{first["id"]}').get_json()['content'] == 'First body'
    page.reload()
    page.wait_for_selector('.sn-ready')
    assert page.locator('#noteContent').input_value() == 'Recover this pending draft'
    page.unroute('**/api/notes/*', fail_save)
    page.locator('#saveNow').click()
    page.wait_for_function("document.querySelector('#saveStatus').textContent === 'Saved'")
    assert client.get(f'/api/notes/{first["id"]}').get_json()['content'] == 'Recover this pending draft'


def test_conflict_recovery_keeps_both_versions(editor):
    page, client, first, _ = editor
    client.patch(f'/api/notes/{first["id"]}', json={'content': 'Other device edit', 'revision': first['revision']})
    page.locator('#noteContent').fill('My local edit')
    page.locator('#saveNow').click()
    page.wait_for_selector('#draftNotice:not(.d-none)')
    page.reload()
    page.wait_for_selector('#draftNotice:not(.d-none)')
    page.locator('#noteContent').fill('My updated local edit')
    page.reload()
    page.wait_for_selector('#draftNotice:not(.d-none)')
    page.locator('#recoverDraft').click()
    page.wait_for_function("document.querySelector('#saveStatus').textContent === 'Saved'")
    notes = client.get('/api/notes').get_json()
    assert len(notes) == 3
    assert {note['content'] for note in notes} >= {'Other device edit', 'My updated local edit'}


def test_tag_names_are_literal_dom_text(editor):
    page, client, first, _ = editor
    tag = '\" autofocus onfocus=alert(1) x=\"'
    client.patch(f'/api/notes/{first["id"]}', json={'tags': [tag]})
    page.reload()
    page.wait_for_selector('#tagList button')
    button = page.locator('#tagList button')
    assert button.get_attribute('data-tag') == tag
    assert button.get_attribute('onfocus') is None
    button.click()
    page.wait_for_function('state.notes.length === 1')


def test_storage_failure_does_not_prevent_editing(editor):
    page, client, first, _ = editor
    page.evaluate("() => { Storage.prototype.setItem = () => { throw new Error('quota'); }; }")
    page.locator('#noteContent').fill('Still saves to server')
    page.locator('#saveNow').click()
    page.wait_for_function("document.querySelector('#saveStatus').textContent === 'Saved'")
    assert client.get(f'/api/notes/{first["id"]}').get_json()['content'] == 'Still saves to server'
