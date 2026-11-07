// Feature counts stay in this browser. No note data or event properties accepted.
const usage = (() => {
  const key = 'stillnote-usage-v1';
  const events = Object.freeze({ app_open: 'App opens', note_open: 'Notes opened', note_create: 'Notes created',
    save: 'Successful saves', save_failure: 'Save failures', save_conflict: 'Save conflicts',
    search: 'Searches', pin: 'Pin changes', archive: 'Archive changes', trash: 'Notes trashed',
    restore: 'Trash restores', export: 'Exports', journal: 'Journal entries', theme: 'Theme changes' });
  function dateKey(date) {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  }
  function read() {
    let raw;
    try { raw = JSON.parse(localStorage.getItem(key)); } catch (_) {}
    const days = {};
    const today = new Date();
    const cutoff = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 89);
    if (raw?.days && typeof raw.days === 'object') {
      for (const [day, counts] of Object.entries(raw.days)) {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || day < dateKey(cutoff) || day > dateKey(today) || !counts || typeof counts !== 'object') continue;
        const cleaned = {};
        for (const name of Object.keys(events)) {
          if (Number.isSafeInteger(counts[name]) && counts[name] > 0) cleaned[name] = counts[name];
        }
        if (Object.keys(cleaned).length) days[day] = cleaned;
      }
    }
    return { version: 1, enabled: raw?.enabled === true, days };
  }
  function write(data) {
    try { localStorage.setItem(key, JSON.stringify(data)); return true; } catch (_) { return false; }
  }
  function record(name) {
    if (!Object.hasOwn(events, name)) return false;
    const data = read();
    if (!data.enabled) return false;
    const day = dateKey(new Date());
    data.days[day] ??= {};
    data.days[day][name] = Math.min(Number.MAX_SAFE_INTEGER, (data.days[day][name] || 0) + 1);
    return write(data);
  }
  function setEnabled(enabled) { const data = read(); data.enabled = enabled === true; return write(data); }
  function clear() { const data = read(); data.days = {}; return write(data); }
  function snapshot() {
    const data = read();
    // Apply retention to persisted data even when collection is disabled.
    try { if (localStorage.getItem(key) !== null) write(data); } catch (_) {}
    return data;
  }
  return { record, setEnabled, clear, snapshot, events };
})();

function downloadJson(data, filename) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url; link.download = filename; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

(() => {
  const dialog = document.getElementById('usageDialog');
  const toggle = document.getElementById('usageEnabled');
  function render() {
    const data = usage.snapshot();
    toggle.checked = data.enabled;
    const totals = {};
    for (const day of Object.values(data.days)) for (const [event, count] of Object.entries(day)) totals[event] = (totals[event] || 0) + count;
    document.getElementById('usageSummary').textContent = `${Object.keys(data.days).length} active days in the last 90 days.`;
    const rows = Object.entries(usage.events).map(([name, label]) => {
      const row = document.createElement('tr');
      for (const value of [label, totals[name] || 0]) { const cell = document.createElement('td'); cell.textContent = value; row.append(cell); }
      return row;
    });
    document.getElementById('usageCounts').replaceChildren(...rows);
  }
  document.getElementById('openUsage').addEventListener('click', () => { render(); dialog.showModal(); });
  document.getElementById('closeUsage').addEventListener('click', () => dialog.close());
  toggle.addEventListener('change', () => {
    if (!usage.setEnabled(toggle.checked)) document.getElementById('usageSummary').textContent = 'Browser storage is unavailable; usage collection could not be changed.';
    else render();
  });
  document.getElementById('clearUsage').addEventListener('click', () => { usage.clear(); render(); });
  document.getElementById('exportUsage').addEventListener('click', () => downloadJson(usage.snapshot(), 'stillnote-usage.json'));
  usage.snapshot();
  usage.record('app_open');
})();
