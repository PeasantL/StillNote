const state = { notes: [], selected: null, view: 'notes', tag: '', search: '', saveTimer: null, listTimer: null, dirty: false, editVersion: 0, saving: null, navigating: false, listRequest: 0, conflict: false };
const storage = {
  get(key) { try { return localStorage.getItem(key); } catch (_) { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); return true; } catch (_) { return false; } },
  remove(key) { try { localStorage.removeItem(key); } catch (_) {} }
};
const DRAFT_PREFIX = 'stillnote-draft-';
const LAST_NOTE_KEY = 'stillnote-last-note';
const el = Object.fromEntries([
  'notesList', 'emptyList', 'emptyEditor', 'editor', 'noteTitle', 'noteTags', 'noteContent',
  'saveStatus', 'saveNow', 'draftNotice', 'recoverDraft', 'discardDraft', 'pinNote', 'archiveNote', 'deleteNote', 'newNote', 'search', 'tagList',
  'tagChips', 'editTags', 'tagEditor', 'doneTags', 'emptyNewNote', 'emptyEditorTitle', 'emptyEditorDescription', 'themeButton', 'openSidebar', 'closeSidebar', 'sidebarScrim', 'backToList', 'messageToast', 'messageText'
].map(id => [id, document.getElementById(id)]));

// Safari's keyboard can resize and pan the visual viewport while leaving vh/dvh
// and the layout viewport unchanged, including in Home Screen web apps.
function trackViewport() {
  const root = document.documentElement;
  const viewport = window.visualViewport;
  let frame;

  function update() {
    frame = null;
    // Keep the layout stable during pinch zoom; the browser handles panning it.
    if (viewport && Math.abs(viewport.scale - 1) > 0.01) return;
    const height = viewport ? viewport.height : window.innerHeight;
    root.style.setProperty('--sn-viewport-height', `${height}px`);
    root.style.setProperty('--sn-viewport-top', `${viewport ? viewport.offsetTop : 0}px`);
    root.classList.toggle('sn-compact-viewport', height < 600);
  }

  function scheduleUpdate() {
    if (frame == null) frame = requestAnimationFrame(update);
  }

  viewport?.addEventListener('resize', scheduleUpdate);
  viewport?.addEventListener('scroll', scheduleUpdate);
  window.addEventListener('resize', scheduleUpdate);
  window.addEventListener('pageshow', scheduleUpdate);
  update();
}

trackViewport();

async function api(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try { message = (await response.json()).error || message; } catch (_) {}
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return response.status === 204 ? null : response.json();
}

function showMessage(message) {
  el.messageText.textContent = message;
  bootstrap.Toast.getOrCreateInstance(el.messageToast, { delay: 2500 }).show();
}

function escapeHtml(value) {
  const span = document.createElement('span');
  span.textContent = value;
  return span.innerHTML;
}

function displayDate(value) {
  const date = new Date(value);
  const today = new Date();
  return date.toDateString() === today.toDateString()
    ? date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : date.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

async function loadNotes() {
  const requestId = ++state.listRequest;
  const parameters = new URLSearchParams({ summary: '1' });
  if (state.view === 'archived') parameters.set('archived', '1');
  if (state.search) parameters.set('q', state.search);
  if (state.tag) parameters.set('tag', state.tag);
  const notes = await api(`/api/notes?${parameters}`);
  if (requestId !== state.listRequest) return;
  state.notes = state.view === 'pinned' ? notes.filter(note => note.pinned) : notes;
  renderNotes();

}

function renderNotes() {
  el.notesList.innerHTML = state.notes.map(note => {
    const preview = (note.preview ?? note.content ?? '').replace(/\s+/g, ' ').trim() || 'Empty note';
    const tags = note.tags.length ? ` · ${note.tags.join(', ')}` : '';
    return `<button class="list-group-item list-group-item-action note-row ${state.selected?.id === note.id ? 'active' : ''}" data-id="${note.id}">
      <div class="d-flex gap-2 align-items-center"><span class="note-row-title flex-grow-1">${note.pinned ? '<svg class="pinned-icon" viewBox="0 0 24 24" role="img" aria-label="Pinned"><path d="M9 3h6l-.75 6 3.25 3v2h-11v-2l3.25-3zM12 14v7"/></svg>' : ''}${escapeHtml(note.title)}</span><span class="note-row-meta">${displayDate(note.updated_at)}</span></div>
      <div class="note-row-preview mt-1">${escapeHtml(preview)}</div>
      ${tags ? `<div class="note-row-meta mt-1">${escapeHtml(tags.replace(/^ · /, ''))}</div>` : ''}
    </button>`;
  }).join('');
  el.emptyList.classList.toggle('d-none', state.notes.length > 0);
  el.emptyList.textContent = state.search ? 'No matching notes.' : state.view === 'pinned' ? 'No pinned notes yet.' : state.view === 'archived' ? 'No archived notes.' : 'No notes here yet.';
}

function renderTagChips() {
  const tags = [...new Set(el.noteTags.value.split(',').map(tag => tag.trim()).filter(Boolean))];
  el.tagChips.replaceChildren(...tags.map(tag => {
    const chip = document.createElement('span');
    chip.className = 'tag-chip';
    chip.textContent = tag;
    return chip;
  }));
  el.editTags.textContent = tags.length ? 'Edit tags' : 'Add tags';
}

function closeTagEditor() {
  el.tagEditor.classList.add('d-none');
  el.editTags.setAttribute('aria-expanded', 'false');
  renderTagChips();
}

function showEmptyEditor() {
  el.editor.classList.add('d-none');
  el.emptyEditor.classList.remove('d-none');
  el.emptyEditorTitle.textContent = state.notes.length ? 'Choose a note' : 'A little space to think';
  el.emptyEditorDescription.textContent = state.notes.length ? 'Open a note from your library, or start a fresh page.' : 'Capture an idea, make a list, or start a fresh page.';
  document.body.classList.remove('mobile-editing');
}

function showEditor(note) {
  state.selected = note;
  storage.set(LAST_NOTE_KEY, String(note.id));
  state.dirty = false;
  state.conflict = false;
  el.saveStatus.textContent = 'Saved';
  el.draftNotice.classList.add('d-none');
  el.noteTitle.value = note.title;
  el.noteContent.value = note.content;
  el.noteTags.value = note.tags.join(', ');
  const draft = readDraft(note.id);
  if (draft) {
    el.noteTitle.value = draft.title;
    el.noteContent.value = draft.content;
    el.noteTags.value = draft.tags;
    state.dirty = true;
    state.editVersion++;
    state.conflict = draft.revision !== note.revision;
    el.saveStatus.textContent = state.conflict ? 'Draft needs review' : 'Recovered unsaved draft';
    el.draftNotice.classList.toggle('d-none', !state.conflict);
  }
  closeTagEditor();
  el.pinNote.setAttribute('aria-pressed', String(note.pinned));
  el.pinNote.textContent = note.pinned ? 'Unpin' : 'Pin';
  el.archiveNote.textContent = note.archived ? 'Restore' : 'Archive';
  el.emptyEditor.classList.add('d-none');
  el.editor.classList.remove('d-none');
  document.body.classList.add('mobile-editing');
  renderNotes();
}

function fields() {
  return { title: el.noteTitle.value, content: el.noteContent.value, tags: el.noteTags.value };
}

function readDraft(id) {
  try {
    const draft = JSON.parse(storage.get(DRAFT_PREFIX + id));
    return draft && typeof draft.title === 'string' && typeof draft.content === 'string'
      && typeof draft.tags === 'string' && Number.isInteger(draft.revision) ? draft : null;
  } catch (_) { return null; }
}

function keepDraft() {
  if (!state.selected || !state.dirty) return true;
  return storage.set(DRAFT_PREFIX + state.selected.id, JSON.stringify({
    ...fields(), revision: state.conflict ? (readDraft(state.selected.id)?.revision ?? state.selected.revision) : state.selected.revision
  }));
}

function lockEditor(locked) {
  [el.noteTitle, el.noteContent, el.noteTags].forEach(input => { input.readOnly = locked; });
}

async function navigate(action) {
  if (state.navigating) return;
  state.navigating = true;
  lockEditor(true);
  try {
    if (await saveNote()) await action();
  } catch (error) { showMessage(error.message); }
  finally { state.navigating = false; lockEditor(false); }
}

async function selectNote(id) {
  await navigate(async () => showEditor(await api(`/api/notes/${id}`)));
}

async function restoreLastOpenedNote() {
  const savedId = Number(storage.get(LAST_NOTE_KEY));
  const note = state.notes.find(candidate => candidate.id === savedId) || state.notes[0];
  if (note) await selectNote(note.id);
  else { storage.remove(LAST_NOTE_KEY); showEmptyEditor(); }
}

async function createNote(initial = {}) {
  await navigate(async () => {
    const note = await api('/api/notes', { method: 'POST', body: JSON.stringify(initial) });
    state.view = 'notes'; state.tag = ''; state.search = ''; el.search.value = '';
    setActiveView();
    await loadNotes();
    showEditor(note);
    el.noteTitle.select();
  });
}

function scheduleSave() {
  if (!state.selected) return;
  state.dirty = true;
  state.editVersion++;
  el.saveStatus.textContent = keepDraft() ? 'Unsaved changes' : 'Unsaved — local recovery unavailable';
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(saveNote, 650);
}

function updateListNote(note) {
  // Invalidate older responses which could put stale summaries back in the list.
  state.listRequest++;
  const matches = note.archived === (state.view === 'archived')
    && (state.view !== 'pinned' || note.pinned)
    && (!state.tag || note.tags.some(tag => tag.toLowerCase() === state.tag.toLowerCase()))
    && (!state.search || `${note.title} ${note.content}`.toLowerCase().includes(state.search.toLowerCase()));
  state.notes = state.notes.filter(candidate => candidate.id !== note.id);
  if (matches) {
    const { content, ...summary } = note;
    state.notes.push({ ...summary, preview: content.slice(0, 240) });
  }
  state.notes.sort((a, b) => Number(b.pinned) - Number(a.pinned)
    || b.updated_at.localeCompare(a.updated_at) || b.id - a.id);
  renderNotes();
}

async function saveNote() {
  clearTimeout(state.saveTimer);
  if (state.saving) return state.saving;
  if (!state.selected || !state.dirty) return true;
  if (state.conflict) { showMessage('Recover your draft as a new note, or discard it to load the saved version.'); return false; }
  state.saving = (async () => {
    try {
      while (state.dirty) {
        const id = state.selected.id;
        const version = state.editVersion;
        const snapshot = fields();
        const previousTags = state.selected.tags.join(', ');
        el.saveStatus.textContent = 'Saving…';
        const updated = await api(`/api/notes/${id}`, {
          method: 'PATCH', body: JSON.stringify({ ...snapshot, revision: state.selected.revision })
        });
        state.selected = updated;
        state.dirty = state.editVersion !== version;
        if (state.dirty) keepDraft();
        else storage.remove(DRAFT_PREFIX + id);
        updateListNote(updated);
        if (previousTags !== updated.tags.join(', ')) await loadTags();
      }
      el.saveStatus.textContent = 'Saved';
      return true;
    } catch (error) {
      state.conflict = error.status === 409;
      el.draftNotice.classList.toggle('d-none', !state.conflict);
      el.saveStatus.textContent = state.conflict ? 'Changed elsewhere — draft kept' : 'Save failed — retry with Save now';
      showMessage(error.message);
      return false;
    } finally { state.saving = null; }
  })();
  return state.saving;
}

async function patchSelected(changes) {
  let success = false;
  await navigate(async () => {
    if (!state.selected) return;
    const updated = await api(`/api/notes/${state.selected.id}`, {
      method: 'PATCH', body: JSON.stringify({ ...changes, revision: state.selected.revision })
    });
    showEditor(updated);
    updateListNote(updated);
    await loadTags();
    success = true;
  });
  return success;
}

async function deleteSelected() {
  if (!state.selected || !confirm(`Permanently delete “${state.selected.title}”?`)) return;
  await navigate(async () => {
    await api(`/api/notes/${state.selected.id}`, { method: 'DELETE' });
    state.selected = null;
    storage.remove(LAST_NOTE_KEY);
    state.view = 'notes'; state.tag = ''; state.search = ''; el.search.value = '';
    setActiveView();
    await Promise.all([loadNotes(), loadTags()]);
    const newestNote = state.notes.reduce((newest, note) => (
      !newest || note.created_at > newest.created_at ? note : newest
    ), null);
    if (newestNote) showEditor(await api(`/api/notes/${newestNote.id}`));
    else {
      showEmptyEditor();
    }
  });
}

async function loadTags() {
  try {
    const tags = await api('/api/tags');
    el.tagList.replaceChildren(...tags.map(tag => {
      const button = document.createElement('button');
      button.className = `nav-link text-start ${state.tag.toLowerCase() === tag.name.toLowerCase() ? 'active' : ''}`;
      button.dataset.tag = tag.name;
      button.append(document.createTextNode(`# ${tag.name} `));
      const count = document.createElement('span');
      count.className = 'float-end opacity-50';
      count.textContent = tag.note_count;
      button.append(count);
      return button;
    }));
  } catch (error) { showMessage(error.message); }
}

function setActiveView() {
  document.querySelectorAll('[data-view]').forEach(button => button.classList.toggle('active', button.dataset.view === state.view && !state.tag));
}

function closeSidebar() { document.body.classList.remove('sidebar-open'); }

function applyTheme(theme) {
  document.documentElement.dataset.bsTheme = theme;
  storage.set('stillnote-theme-v2', theme);
  const nextTheme = theme === 'dark' ? 'light' : 'dark';
  const label = `Use ${nextTheme} theme`;
  el.themeButton.setAttribute('aria-label', label);
  el.themeButton.title = label;
}

el.notesList.addEventListener('click', event => {
  const row = event.target.closest('[data-id]');
  if (row) selectNote(Number(row.dataset.id));
});
el.newNote.addEventListener('click', () => createNote());
el.emptyNewNote.addEventListener('click', () => createNote());
el.editTags.addEventListener('click', () => {
  const opening = el.tagEditor.classList.contains('d-none');
  el.tagEditor.classList.toggle('d-none', !opening);
  el.editTags.setAttribute('aria-expanded', String(opening));
  if (opening) el.noteTags.focus();
});
el.doneTags.addEventListener('click', () => { closeTagEditor(); el.editTags.focus(); });
el.noteTags.addEventListener('keydown', event => {
  if (event.key === 'Enter' || event.key === 'Escape') {
    event.preventDefault(); closeTagEditor(); el.editTags.focus();
  }
});
el.noteTitle.addEventListener('input', scheduleSave);
el.noteContent.addEventListener('input', scheduleSave);
el.noteTags.addEventListener('input', () => { renderTagChips(); scheduleSave(); });
el.pinNote.addEventListener('click', () => patchSelected({ pinned: !state.selected.pinned }));
el.archiveNote.addEventListener('click', async () => {
  if (!state.selected || !await patchSelected({ archived: !state.selected.archived })) return;
  state.selected = null; document.body.classList.remove('mobile-editing');
  el.editor.classList.add('d-none'); el.emptyEditor.classList.remove('d-none');
  await loadNotes();
});
el.deleteNote.addEventListener('click', deleteSelected);
el.search.addEventListener('input', () => {
  clearTimeout(state.listTimer);
  state.listTimer = setTimeout(async () => { state.search = el.search.value.trim(); try { await loadNotes(); } catch (error) { showMessage(error.message); } }, 200);
});
document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', async () => {
  await navigate(async () => {
    state.view = button.dataset.view; state.tag = ''; setActiveView(); closeSidebar();
    await Promise.all([loadNotes(), loadTags()]);
  });
}));
el.tagList.addEventListener('click', async event => {
  const button = event.target.closest('[data-tag]');
  if (!button) return;
  await navigate(async () => {
    state.tag = button.dataset.tag; state.view = 'notes'; setActiveView(); closeSidebar();
    await Promise.all([loadNotes(), loadTags()]);
  });
});
el.themeButton.addEventListener('click', () => applyTheme(document.documentElement.dataset.bsTheme === 'dark' ? 'light' : 'dark'));
el.openSidebar.addEventListener('click', () => document.body.classList.add('sidebar-open'));
el.closeSidebar.addEventListener('click', closeSidebar);
el.sidebarScrim.addEventListener('click', closeSidebar);
el.backToList.addEventListener('click', () => document.body.classList.remove('mobile-editing'));
document.addEventListener('keydown', event => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'n') { event.preventDefault(); createNote(); }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); clearTimeout(state.saveTimer); saveNote(); }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); el.search.focus(); }
});

el.saveNow.addEventListener('click', saveNote);
el.recoverDraft.addEventListener('click', async () => {
  if (state.navigating || state.saving || !state.selected) return;
  state.navigating = true;
  lockEditor(true);
  try {
    const originalId = state.selected.id;
    const note = await api('/api/notes', { method: 'POST', body: JSON.stringify(fields()) });
    storage.remove(DRAFT_PREFIX + originalId);
    showEditor(note);
    state.view = 'notes'; state.tag = ''; state.search = ''; el.search.value = ''; setActiveView();
    await Promise.all([loadNotes(), loadTags()]);
    showMessage('Draft recovered as a new note. The original is unchanged.');
  } catch (error) { showMessage(error.message); }
  finally { state.navigating = false; lockEditor(false); }
});
el.discardDraft.addEventListener('click', async () => {
  if (state.navigating || state.saving || !state.selected || !confirm('Discard your local draft and load the saved version?')) return;
  state.navigating = true;
  lockEditor(true);
  try {
    const note = await api(`/api/notes/${state.selected.id}`);
    storage.remove(DRAFT_PREFIX + note.id);
    showEditor(note);
  } catch (error) { showMessage(error.message); }
  finally { state.navigating = false; lockEditor(false); }
});
window.addEventListener('beforeunload', event => {
  if (!state.dirty) return;
  keepDraft(); event.preventDefault(); event.returnValue = '';
});
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') { keepDraft(); saveNote(); }
});
window.addEventListener('online', () => { if (state.dirty) saveNote(); });
const savedTheme = storage.get('stillnote-theme-v2');
const startupStarted = performance.now();

function revealApp() {
  const delay = Math.max(0, 300 - (performance.now() - startupStarted));
  setTimeout(() => requestAnimationFrame(() => {
    document.documentElement.classList.remove('sn-loading');
    document.documentElement.classList.add('sn-ready');
    document.querySelector('.app-shell')?.setAttribute('aria-busy', 'false');
  }), delay);
}

window.addEventListener('pageshow', event => {
  if (event.persisted) revealApp();
});

applyTheme(savedTheme || 'dark');
Promise.all([loadNotes(), loadTags()])
  .then(restoreLastOpenedNote)
  .catch(error => showMessage(error.message))
  .finally(revealApp);
