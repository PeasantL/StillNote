const state = { notes: [], selected: null, view: 'notes', tag: '', search: '', saveTimer: null, listTimer: null };
const el = Object.fromEntries([
  'notesList', 'emptyList', 'emptyEditor', 'editor', 'noteTitle', 'noteTags', 'noteContent',
  'saveStatus', 'pinNote', 'archiveNote', 'deleteNote', 'newNote', 'search', 'tagList',
  'themeButton', 'openSidebar', 'closeSidebar', 'sidebarScrim', 'backToList', 'messageToast', 'messageText'
].map(id => [id, document.getElementById(id)]));

async function api(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try { message = (await response.json()).error || message; } catch (_) {}
    throw new Error(message);
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

async function loadNotes({ keepSelection = true } = {}) {
  const parameters = new URLSearchParams();
  if (state.view === 'archived') parameters.set('archived', '1');
  if (state.search) parameters.set('q', state.search);
  if (state.tag) parameters.set('tag', state.tag);
  const notes = await api(`/api/notes?${parameters}`);
  state.notes = state.view === 'pinned' ? notes.filter(note => note.pinned) : notes;
  renderNotes();
  if (keepSelection && state.selected) {
    const refreshed = state.notes.find(note => note.id === state.selected.id);
    if (refreshed) state.selected = refreshed;
  }
}

function renderNotes() {
  el.notesList.innerHTML = state.notes.map(note => {
    const preview = note.content.replace(/\s+/g, ' ').trim() || 'Empty note';
    const tags = note.tags.length ? ` · ${note.tags.join(', ')}` : '';
    return `<button class="list-group-item list-group-item-action note-row ${state.selected?.id === note.id ? 'active' : ''}" data-id="${note.id}">
      <div class="d-flex gap-2 align-items-center"><span class="note-row-title flex-grow-1">${note.pinned ? '● ' : ''}${escapeHtml(note.title)}</span><span class="note-row-meta">${displayDate(note.updated_at)}</span></div>
      <div class="note-row-preview mt-1">${escapeHtml(preview)}</div>
      <div class="note-row-meta mt-1">${escapeHtml(tags.replace(/^ · /, ''))}</div>
    </button>`;
  }).join('');
  el.emptyList.classList.toggle('d-none', state.notes.length > 0);
}

function showEditor(note) {
  state.selected = note;
  el.noteTitle.value = note.title;
  el.noteContent.value = note.content;
  el.noteTags.value = note.tags.join(', ');
  el.pinNote.textContent = note.pinned ? 'Unpin' : 'Pin';
  el.archiveNote.textContent = note.archived ? 'Restore' : 'Archive';
  el.emptyEditor.classList.add('d-none');
  el.editor.classList.remove('d-none');
  document.body.classList.add('mobile-editing');
  renderNotes();
}

async function selectNote(id) {
  try { showEditor(await api(`/api/notes/${id}`)); }
  catch (error) { showMessage(error.message); }
}

async function createNote() {
  try {
    const note = await api('/api/notes', { method: 'POST', body: '{}' });
    state.view = 'notes'; state.tag = ''; state.search = ''; el.search.value = '';
    setActiveView();
    await Promise.all([loadNotes({ keepSelection: false }), loadTags()]);
    showEditor(note);
    el.noteTitle.select();
  } catch (error) { showMessage(error.message); }
}

function scheduleSave() {
  if (!state.selected) return;
  el.saveStatus.textContent = 'Unsaved changes';
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(saveNote, 650);
}

async function saveNote() {
  if (!state.selected) return;
  const id = state.selected.id;
  el.saveStatus.textContent = 'Saving…';
  try {
    const updated = await api(`/api/notes/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ title: el.noteTitle.value, content: el.noteContent.value, tags: el.noteTags.value })
    });
    if (state.selected?.id === id) {
      state.selected = updated;
      el.saveStatus.textContent = 'Saved';
    }
    await Promise.all([loadNotes(), loadTags()]);
  } catch (error) {
    el.saveStatus.textContent = 'Save failed';
    showMessage(error.message);
  }
}

async function patchSelected(changes) {
  if (!state.selected) return;
  clearTimeout(state.saveTimer);
  await saveNote();
  try {
    const updated = await api(`/api/notes/${state.selected.id}`, { method: 'PATCH', body: JSON.stringify(changes) });
    showEditor(updated);
    await Promise.all([loadNotes(), loadTags()]);
  } catch (error) { showMessage(error.message); }
}

async function deleteSelected() {
  if (!state.selected || !confirm(`Permanently delete “${state.selected.title}”?`)) return;
  try {
    await api(`/api/notes/${state.selected.id}`, { method: 'DELETE' });
    state.selected = null;
    el.editor.classList.add('d-none'); el.emptyEditor.classList.remove('d-none');
    document.body.classList.remove('mobile-editing');
    await Promise.all([loadNotes(), loadTags()]);
  } catch (error) { showMessage(error.message); }
}

async function loadTags() {
  try {
    const tags = await api('/api/tags');
    el.tagList.innerHTML = tags.map(tag => `<button class="nav-link text-start ${state.tag.toLowerCase() === tag.name.toLowerCase() ? 'active' : ''}" data-tag="${escapeHtml(tag.name)}"># ${escapeHtml(tag.name)} <span class="float-end opacity-50">${tag.note_count}</span></button>`).join('');
  } catch (error) { showMessage(error.message); }
}

function setActiveView() {
  document.querySelectorAll('[data-view]').forEach(button => button.classList.toggle('active', button.dataset.view === state.view && !state.tag));
}

function closeSidebar() { document.body.classList.remove('sidebar-open'); }

function applyTheme(theme) {
  document.documentElement.dataset.bsTheme = theme;
  localStorage.setItem('stillnote-theme-v2', theme);
  const nextTheme = theme === 'dark' ? 'light' : 'dark';
  const label = `Use ${nextTheme} theme`;
  el.themeButton.setAttribute('aria-label', label);
  el.themeButton.title = label;
}

el.notesList.addEventListener('click', event => {
  const row = event.target.closest('[data-id]');
  if (row) selectNote(Number(row.dataset.id));
});
el.newNote.addEventListener('click', createNote);
el.noteTitle.addEventListener('input', scheduleSave);
el.noteContent.addEventListener('input', scheduleSave);
el.noteTags.addEventListener('input', scheduleSave);
el.pinNote.addEventListener('click', () => patchSelected({ pinned: !state.selected.pinned }));
el.archiveNote.addEventListener('click', async () => {
  await patchSelected({ archived: !state.selected.archived });
  state.selected = null; document.body.classList.remove('mobile-editing');
  el.editor.classList.add('d-none'); el.emptyEditor.classList.remove('d-none');
  await loadNotes();
});
el.deleteNote.addEventListener('click', deleteSelected);
el.search.addEventListener('input', () => {
  clearTimeout(state.listTimer);
  state.listTimer = setTimeout(async () => { state.search = el.search.value.trim(); await loadNotes({ keepSelection: false }); }, 200);
});
document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', async () => {
  state.view = button.dataset.view; state.tag = ''; setActiveView(); closeSidebar();
  await Promise.all([loadNotes({ keepSelection: false }), loadTags()]);
}));
el.tagList.addEventListener('click', async event => {
  const button = event.target.closest('[data-tag]');
  if (!button) return;
  state.tag = button.dataset.tag; state.view = 'notes'; setActiveView(); closeSidebar();
  await Promise.all([loadNotes({ keepSelection: false }), loadTags()]);
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

const savedTheme = localStorage.getItem('stillnote-theme-v2');
applyTheme(savedTheme || 'dark');
Promise.all([loadNotes(), loadTags()]).catch(error => showMessage(error.message));
