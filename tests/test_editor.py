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


def test_usage_is_opt_in_and_counts_no_note_data(editor):
    page, _, _, _ = editor
    assert page.evaluate("localStorage.getItem('stillnote-usage-v1')") is None
    assert page.evaluate("usage.record('note_create')") is False
    page.locator('#openUsage').click()
    page.locator('#usageEnabled').check()
    page.locator('#closeUsage').click()
    page.locator('#newNote').click()
    page.wait_for_function("document.querySelector('#noteTitle').value === 'Untitled note'")
    assert page.evaluate("usage.record('a private search term')") is False
    snapshot = page.evaluate('usage.snapshot()')
    assert snapshot['enabled'] is True
    assert sum(day.get('note_create', 0) for day in snapshot['days'].values()) == 1
    assert 'Untitled' not in str(snapshot)
    page.locator('#openUsage').click()
    with page.expect_download() as download:
        page.locator('#exportUsage').click()
    assert download.value.suggested_filename == 'stillnote-usage.json'
    page.locator('#usageEnabled').uncheck()
    assert page.evaluate("usage.record('save')") is False
    page.locator('#clearUsage').click()
    assert page.evaluate('usage.snapshot().days') == {}


def test_usage_retention_and_storage_failure(editor):
    page, _, _, _ = editor
    page.evaluate("""() => {
      localStorage.setItem('stillnote-usage-v1', JSON.stringify({ enabled: true, days: {
        '2000-01-01': {save: 9}, '2999-01-01': {save: 9}
      }}));
    }""")
    assert page.evaluate('usage.snapshot().days') == {}
    page.evaluate("() => { Storage.prototype.setItem = () => { throw new Error('quota'); }; }")
    assert page.evaluate("usage.record('save')") is False


def test_trash_restore_and_journal_capture(editor):
    page, client, first, _ = editor
    page.locator('[aria-label="More note actions"]').click()
    page.locator('#deleteNote').click()
    page.wait_for_function('state.selected === null')
    page.locator('[data-view="trash"]').click()
    page.wait_for_function("state.view === 'trash' && state.notes.length === 1")
    page.locator(f'[data-id="{first["id"]}"]').click()
    page.wait_for_function("document.querySelector('#noteContent').readOnly")
    assert page.locator('#noteContent').input_value() == 'First body'
    page.locator('[aria-label="More note actions"]').click()
    page.locator('#restoreTrash').click()
    page.wait_for_function('state.selected === null && state.notes.length === 0')
    assert client.get(f'/api/notes/{first["id"]}').get_json()['content'] == 'First body'
    page.locator('#newJournal').click()
    page.wait_for_function("document.querySelector('#noteTitle').value.startsWith('Diary - ')")
    assert client.get('/api/notes').get_json()[0]['tags'] == ['Diary']
    assert page.locator('#noteContent').get_attribute('readonly') is None


def test_search_ignores_response_from_older_query(editor):
    page, _, _, second = editor
    held = []

    def delay_first_search(route):
        if 'q=First' in route.request.url:
            held.append((route, route.fetch()))
        else:
            route.continue_()

    page.route('**/api/notes?**', delay_first_search)
    page.locator('#search').fill('First')
    page.wait_for_function("state.search === 'First'")
    page.locator('#search').fill('Second')
    page.wait_for_function("state.search === 'Second' && state.notes.length === 1 && state.notes[0].title === 'Second'")
    route, response = held[0]
    with page.expect_response(lambda response: 'q=First' in response.url):
        route.fulfill(response=response)
    page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
    assert page.locator('#notesList [data-id]').get_attribute('data-id') == str(second['id'])


def test_history_preview_and_restore(editor):
    page, client, first, _ = editor
    page.locator('#noteContent').fill('Newer writing')
    page.locator('#saveNow').click()
    page.wait_for_function("document.querySelector('#saveStatus').textContent === 'Saved'")
    page.locator('[aria-label="More note actions"]').click()
    page.locator('#openHistory').click()
    page.wait_for_selector('#historyDialog[open]')
    assert 'First body' in page.locator('#historyPreview').input_value()
    page.locator('#restoreHistory').click()
    page.wait_for_function("document.querySelector('#noteContent').value === 'First body'")
    assert client.get(f'/api/notes/{first["id"]}/history').get_json()[0]['id'] > 1


def test_json_import_from_file(editor):
    import json
    page, client, _, _ = editor
    backup = client.get('/export/notes.json').get_json()
    page.on('dialog', lambda dialog: dialog.accept())
    page.locator('#importFile').set_input_files({'name': 'backup.json', 'mimeType': 'application/json', 'buffer': json.dumps(backup).encode()})
    page.wait_for_function('state.notes.length === 4')
    assert len(client.get('/api/notes').get_json()) == 4


def test_library_pagination_sort_and_filter_reset(editor):
    page, client, _, _ = editor
    for index in range(105):
        client.post('/api/notes', json={'title': f'Batch {index:03}'})
    page.reload()
    page.wait_for_selector('.sn-ready')
    page.wait_for_function('state.notes.length === 100')
    assert page.locator('#resultCount').text_content() == '107 notes'
    page.locator('#loadMore').click()
    page.wait_for_function('state.notes.length === 107')
    page.locator('#sortNotes').select_option('title')
    page.wait_for_function("state.notes.length === 100 && state.notes[0].title === 'Batch 000'")
    page.locator('#search').fill('Batch 099')
    page.wait_for_function('state.notes.length === 1')
    page.locator('#clearFilters').click()
    page.wait_for_function('state.notes.length === 100')
    assert page.locator('#search').input_value() == ''


def test_narrow_navigation_focus_and_escape(editor):
    page, _, _, _ = editor
    page.set_viewport_size({'width': 600, 'height': 500})
    page.locator('#backToList').click()
    page.locator('#openSidebar').click()
    assert page.locator('#openSidebar').get_attribute('aria-expanded') == 'true'
    page.locator('#openUsage').focus()
    page.keyboard.press('Tab')
    page.keyboard.press('Tab')
    assert page.locator('.brand').evaluate('el => el === document.activeElement')
    page.keyboard.press('Escape')
    assert page.locator('#notesSidebar').evaluate('el => el.inert')
    assert page.locator('#openSidebar').evaluate('el => el === document.activeElement')
