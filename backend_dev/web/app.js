import { createBridge, whenHostReady } from './lib/bridge.js';
import { catalogNote, modelBadge, pickerOptions, sameModelOrder, normalizeModelOrder, modelOrderIssue, moveModelOrder, syncModelOrderDraft } from './lib/models.js';
import { createStore, applyEvent, acceptsEvent } from './lib/store.js';
import { shouldToastInserted, recoveryButtons, canDiscard } from './lib/view.js';
import { termSaveEnabled, instructionsDirty, micDeviceId, micSelection, micTestRunningAfter, micTestEnded } from './lib/forms.js';
import { messageFor } from './lib/messages.js';
import { createWaveform } from './waveform.js';
import { normalizeSecret } from './lib/secrets.js';
import { toBinding, formatBinding } from './lib/shortcuts.js';

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
let state = createStore();
let currentRun = null;
let historyFilter = 'all';
let editingTermId = null;
let lastMicLevelAt = null;
let lastSavedInstructions = null;
// The bridge handles previous_session_token by fetching a fresh snapshot; onSnapshot installs it here.
const bridge = createBridge(window, { onSnapshot(snapshot) { state = { ...createStore(snapshot), secrets: snapshot.secrets }; currentRun = snapshot.active_run_id; render(); } });
const icon = (name) => `<svg class="i"><use href="#i-${name}"/></svg>`;
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch]);
const waveform = $('#wave') ? createWaveform($('#wave'), () => getComputedStyle($('#dictate')).getPropertyValue('--wave-color').trim()) : null;

function toast(kind, title, body = '') {
  const host = $('#toasts'); if (!host) return;
  const node = document.createElement('div'); node.className = `toast ${kind}`; node.setAttribute('role', kind === 'danger' ? 'alert' : 'status');
  node.innerHTML = `<span class="toast-icon">${icon(kind === 'success' ? 'check-circle' : kind === 'warning' ? 'alert' : 'info')}</span><div><strong>${esc(title)}</strong><span class="muted">${esc(body)}</span></div>`;
  host.append(node);
  // presentation-timer: dismiss a visible notification.
  setTimeout(() => { node.classList.add('is-leaving'); setTimeout(() => node.remove(), 200); }, 4000);
}
function failed(result) { if (!result?.ok) toast('danger', messageFor(result?.error)); return !result?.ok; }
function run() { return state.runs.find((item) => item.run_id === (state.active_run_id ?? currentRun)) ?? state.runs[0] ?? null; }
function applyTheme() {
  const theme = state.settings.theme ?? 'light';
  document.documentElement.dataset.theme = theme === 'system' ? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : theme;
  $$('#theme-seg [data-theme-set]').forEach((button) => button.setAttribute('aria-checked', String(button.dataset.themeSet === theme)));
}
function page(id) {
  if (id === 'models') void refreshCatalog();
  $$('.page').forEach((el) => el.classList.toggle('is-active', el.id === `page-${id}`));
  $$('.nav-item[data-page]').forEach((el) => el.dataset.page === id ? el.setAttribute('aria-current', 'page') : el.removeAttribute('aria-current'));
  const active = $(`#page-${id}`); if (active) { $('#crumb').textContent = active.dataset.title; $('#main').scrollTop = 0; }
}
function dateLabel(value) { if (!value) return ''; const date = new Date(value * 1000); return Number.isNaN(date.valueOf()) ? '' : date.toLocaleString(); }
function renderHistory() {
  const list = $('#history-list'); const recent = $('#recent-list');
  if (!list) return;
  const rows = state.history.filter((item) => historyFilter === 'all' || (historyFilter === 'failed' ? item.status === 'awaiting_cleanup_choice' || item.status === 'error' || item.status === 'held' : item.status === 'done'));
  const html = (items) => items.map((item) => {
    const status = item.status === 'awaiting_cleanup_choice' || item.status === 'held' ? 'failed' : item.status === 'done' ? 'cleaned' : 'raw';
    return `<div class="item ${status === 'failed' ? 'is-failed' : ''}" data-run-id="${esc(item.run_id)}"><span class="app-tile">W</span><div class="item-body"><div class="item-meta"><strong>Wispr Clone</strong><span>·</span><span>${esc(dateLabel(item.created_at))}</span><span class="badge ${status === 'failed' ? 'warning' : 'accent'}">${esc(item.status === 'held' ? 'Not pasted' : status === 'failed' ? 'Needs attention' : status === 'cleaned' ? 'Complete' : 'Dictation')}</span></div><div class="item-text">${esc(item.text ?? '')}</div></div><div class="item-actions"><button class="btn btn-ghost btn-icon btn-sm" data-copy="${esc(item.run_id)}" title="Copy" aria-label="Copy">${icon('copy')}</button><button class="btn btn-ghost btn-icon btn-sm danger" data-delete="${esc(item.run_id)}" title="Delete" aria-label="Delete">${icon('trash')}</button></div></div>`;
  }).join('');
  list.innerHTML = html(rows) || '<div class="empty"><h3>No dictations yet</h3><p class="muted">Your dictations will appear here.</p></div>';
  if (recent) recent.innerHTML = html(state.history.slice(0, 3)) || '<div class="empty"><h3>No dictations yet</h3></div>';
  $('#hist-count').textContent = state.history.length; $('#hist-nav-count').textContent = state.history.length;
  $('.nav-item[data-page="history"] .status-dot').hidden = !state.history.some((item) => item.status === 'awaiting_cleanup_choice' || item.status === 'held');
}
function renderDictionary() {
  const body = $('#dict-body'); if (!body) return;
  const q = ($('#dict-search')?.value ?? '').toLowerCase();
  const rows = state.dictionary.filter((entry) => `${entry.spelling} ${(entry.aliases ?? []).join(' ')}`.toLowerCase().includes(q));
  body.innerHTML = rows.map((entry) => `<tr><td class="term">${esc(entry.spelling)}</td><td><div class="chips">${(entry.aliases ?? []).map((alias) => `<span class="chip">${esc(alias)}</span>`).join('') || '<span class="faint">—</span>'}</div></td><td class="faint"></td><td class="actions"><div><button class="btn btn-ghost btn-icon btn-sm" aria-label="Edit ${esc(entry.spelling)}" data-edit-term="${esc(entry.id)}">${icon('pencil')}</button><button class="btn btn-ghost btn-icon btn-sm danger" aria-label="Delete ${esc(entry.spelling)}" data-delete-term="${esc(entry.id)}">${icon('trash')}</button></div></td></tr>`).join('');
  $('#dict-empty').hidden = rows.length > 0; $('.table thead').style.display = rows.length ? '' : 'none'; $('#dict-count').textContent = state.dictionary.length;
}
// Live model lists are fetched through the host when the page opens.
let modelCatalog = null;
let catalogRequest = 0;
let statusRequest = 0;
let nvidiaFallbackDraft = null;
let lastSavedNvidiaOrder = null;
let renderedNvidiaOrder = null;
let nvidiaOrderSaving = false;
let nvidiaKeyBusy = false;
const cleanupProvider = () => state.settings.cleanup_provider ?? 'lmstudio';
async function refreshCatalog() {
  const request = ++catalogRequest;
  const provider = cleanupProvider();
  const result = await bridge.call('models_catalog');
  if (result?.ok && request === catalogRequest && provider === cleanupProvider()) { modelCatalog = result.data; renderModels(); }
  return result;
}
async function refreshModelStatus() {
  const request = ++statusRequest;
  const selection = JSON.stringify([cleanupProvider(), state.settings.cleanup_model_id, state.settings.nvidia_cleanup_model_ids]);
  const result = await bridge.call('models_status');
  if (result?.ok && request === statusRequest && selection === JSON.stringify([cleanupProvider(), state.settings.cleanup_model_id, state.settings.nvidia_cleanup_model_ids])) { state.models = result.data.models ?? []; renderModels(); }
}
function renderFallbackState() {
  const draft = nvidiaFallbackDraft ?? [];
  const issue = modelOrderIssue(draft);
  const dirty = !sameModelOrder(normalizeModelOrder(draft), lastSavedNvidiaOrder ?? []);
  const save = $('#save-nvidia-models'); if (save) save.disabled = nvidiaOrderSaving || Boolean(issue) || !dirty;
  const add = $('#add-nvidia-model'); if (add) add.disabled = nvidiaOrderSaving || draft.length >= 12;
  const note = $('#nvidia-fallback-note'); if (note) note.textContent = issue || (nvidiaOrderSaving ? 'Saving order…' : dirty ? 'Changes apply after Save order.' : 'Models are tried in the saved order.');
  $$('[data-fallback-action]').forEach((button) => { const index = Number(button.dataset.index); button.disabled = nvidiaOrderSaving || (button.dataset.fallbackAction === 'up' && index === 0) || (button.dataset.fallbackAction === 'down' && index === draft.length - 1) || (button.dataset.fallbackAction === 'remove' && draft.length === 1); });
  $$('[data-fallback-index]').forEach((input) => { input.disabled = nvidiaOrderSaving; });
}
function renderFallbackOrder() {
  const saved = state.settings.nvidia_cleanup_model_ids ?? [];
  nvidiaFallbackDraft = syncModelOrderDraft(nvidiaFallbackDraft, lastSavedNvidiaOrder, saved);
  lastSavedNvidiaOrder = [...saved];
  const list = $('#nvidia-fallback-list');
  if (list && !sameModelOrder(renderedNvidiaOrder, nvidiaFallbackDraft)) {
    list.innerHTML = nvidiaFallbackDraft.map((id, index) => `<li class="fallback-row"><span class="fallback-step" aria-hidden="true">${index + 1}</span><label class="field"><input value="${esc(id)}" data-fallback-index="${index}" aria-label="Cleanup model ${index + 1}" list="nvidia-catalog-options" autocomplete="off" spellcheck="false" placeholder="provider/model-id"></label><div class="fallback-actions"><button class="btn btn-ghost btn-icon fallback-up" data-fallback-action="up" data-index="${index}" aria-label="Move cleanup model ${index + 1} up" title="Move up">${icon('chevron')}</button><button class="btn btn-ghost btn-icon" data-fallback-action="down" data-index="${index}" aria-label="Move cleanup model ${index + 1} down" title="Move down">${icon('chevron')}</button><button class="btn btn-ghost btn-icon danger" data-fallback-action="remove" data-index="${index}" aria-label="Remove cleanup model ${index + 1}" title="Remove">${icon('x')}</button></div></li>`).join('');
    renderedNvidiaOrder = [...nvidiaFallbackDraft];
  }
  const suggestions = $('#nvidia-catalog-options');
  if (suggestions) suggestions.replaceChildren(...(modelCatalog?.cleanup?.provider === 'nvidia' ? modelCatalog.cleanup.models ?? [] : []).filter((model) => !model.missing).map((model) => { const option = document.createElement('option'); option.value = model.model_id; option.label = model.display_name || model.model_id; return option; }));
  renderFallbackState();
}
function renderModels() {
  const provider = cleanupProvider();
  const providerSelect = $('#cleanup-provider'); if (providerSelect && document.activeElement !== providerSelect) providerSelect.value = provider;
  const cloud = provider === 'nvidia';
  const localPanel = $('#cleanup-local-model'); if (localPanel) localPanel.hidden = cloud;
  const cloudPanel = $('#cleanup-nvidia'); if (cloudPanel) cloudPanel.hidden = !cloud;
  const providerNote = $('#cleanup-provider-note'); if (providerNote) providerNote.textContent = cloud ? 'Transcript text, cleanup instructions, and dictionary spellings are sent to NVIDIA.' : 'Cleanup runs on this device.';
  const keyStatus = $('#nvidia-key-status'); if (keyStatus) keyStatus.textContent = state.secrets?.nvidia_api_key?.configured ? 'Key saved · model availability is checked during cleanup.' : 'No key saved';
  renderFallbackOrder();
  $$('.model-card').forEach((card) => {
    const role = card.dataset.model === 'cleanup' ? 'cleanup' : 'stt';
    const model = state.models.find((item) => item.role === role);
    const current = role === 'cleanup' && cloud ? state.settings.nvidia_cleanup_model_ids?.[0] : model?.model_id ?? state.settings?.[`${role}_model_id`];
    const badge = $('[data-status]', card);
    const select = $('[data-select]', card);
    if (select && !(role === 'cleanup' && cloud) && document.activeElement !== select) {
      select.replaceChildren(...pickerOptions(role, modelCatalog, current).map((item) => { const option = document.createElement('option'); option.value = item.value; option.textContent = item.label; option.selected = item.selected; return option; }));
      select.disabled = !modelCatalog;
    }
    const modelId = $('[data-model-id]', card); if (modelId) modelId.textContent = current ?? '';
    const where = $('[data-where]', card); if (where) where.textContent = role === 'stt' ? 'Leaves this device' : cloud ? 'Leaves this device (NVIDIA)' : 'On this device (LM Studio)';
    const note = $('[data-catalog-note]', card); if (note) note.textContent = catalogNote(role, modelCatalog, role === 'cleanup' ? provider : undefined);
    if (badge) { const view = modelBadge(model, messageFor, role === 'cleanup' ? provider : undefined); badge.className = `badge ${view.tone}`; badge.textContent = view.text; }
  });
  const dot = $('.nav-item[data-page="models"] .status-dot');
  if (dot) dot.hidden = !state.models.some((item) => !item.ready);
}
function renderRun() {
  const active = run(); const status = active?.status ?? 'idle';
  const card = $('#dictate');
  if (!card) return;
  card.dataset.state = status === 'recording' ? 'recording' : status === 'processing' ? 'processing' : status === 'error' || status === 'uncertain' || status === 'awaiting_cleanup_choice' || status === 'held' ? 'warning' : 'idle';
  const recording = status === 'recording'; const pending = ['processing', 'awaiting_destination'].includes(status);
  $('#dictate-status').textContent = recording ? 'Listening' : status === 'awaiting_destination' ? 'Waiting to paste' : pending ? 'Working' : status === 'held' ? 'Text not pasted' : status === 'awaiting_cleanup_choice' ? 'Needs attention' : status === 'error' || status === 'uncertain' ? 'Could not confirm' : 'Ready when you are';
  $('#dictate-eyebrow').textContent = recording ? 'Listening' : 'Backend status';
  $('#dictate-caption').textContent = recording ? 'Go ahead — say it the way you would to a friend.' : 'From a passing thought to the perfect words.';
  const btn = $('#rec-btn'); btn.disabled = !bridge.available() || pending || ['awaiting_cleanup_choice', 'awaiting_destination'].includes(status);
  btn.innerHTML = recording ? `${icon('stop')}<span>Finish dictation</span>` : `${icon('mic')}<span>Start dictation</span>`;
  $('#dictate-hint').textContent = bridge.available() ? '' : 'Not connected';
  $('#dictate-cancel').hidden = !canDiscard(status);
  if (state.lastEvent && shouldToastInserted(state.lastEvent)) { toast('success', 'Dictation inserted', 'The backend confirmed delivery.'); state.lastEvent = null; }
  if ($('#dictate-recovery')) $('#dictate-recovery').innerHTML = ['awaiting_cleanup_choice', 'held', 'awaiting_destination'].includes(status) && active
    ? recoveryButtons(active).map((action) => `<button class="btn btn-secondary btn-sm" data-recover="${esc(action)}">${esc(action.replaceAll('_', ' '))}</button>`).join('') : '';
  if (status === 'awaiting_cleanup_choice') $('#dictate-caption').textContent = "Text cleanup couldn't finish. Choose how to continue.";
  if (status === 'awaiting_destination') $('#dictate-caption').textContent = 'Return to the original text field to finish pasting.';
  if (status === 'held') $('#dictate-caption').textContent = 'Automatic paste could not finish in the original text field. Use Copy to paste your text where you want.';
  const level = state.latestLevel; waveform?.update(level?.bands ?? [], recording && level?.run_id === active?.run_id);
  const meter = $('#level-segments');
  if (meter) { const count = Math.round(36 * Math.max(0, Math.min(1, Math.max(...(level?.run_id === null ? level.bands ?? [] : [0]))))); meter.innerHTML = '<i></i>'.repeat(36); $$('i', meter).forEach((segment, index) => { if (index < count) segment.className = index >= 29 ? 'warm' : 'on'; }); if (level?.run_id === null) $('#level-state').textContent = 'Receiving microphone levels'; }

}
function renderSettings() {
  applyTheme();
  const settings = state.settings;
  $('#cleanup-switch')?.setAttribute('aria-checked', String(Boolean(settings.cleanup_enabled)));
  $('#sound-switch')?.setAttribute('aria-checked', String(Boolean(settings.sound_cues)));
  const instructions = $('#instructions');
  const savedInstructions = settings.cleanup_instructions ?? '';
  if (instructions && (lastSavedInstructions === null || instructions.value === lastSavedInstructions)) instructions.value = savedInstructions;
  lastSavedInstructions = savedInstructions;
  const saveInstructions = $('#save-instructions');
  if (saveInstructions) saveInstructions.disabled = !instructionsDirty(instructions?.value ?? '', savedInstructions);
  const devices = state.microphones ?? [];
  const micSelect = $('#mic-select');
  if (micSelect && document.activeElement !== micSelect) micSelect.value = micSelection(settings, devices);
  const keyConfigured = state.secrets?.openrouter_api_key?.configured;
  const keyStatus = $('#openrouter-key-status'); if (keyStatus) keyStatus.textContent = keyConfigured ? 'Key saved' : 'No key saved';
  $$('#mode-seg [data-mode]').forEach((button) => button.setAttribute('aria-checked', String(button.dataset.mode === settings.recording_mode)));
  const shortcut = $('#shortcut-current'); if (shortcut) shortcut.textContent = formatBinding(settings.dictation_shortcut ?? 'ctrl+shift+space');
}
function render() { renderRun(); renderModels(); renderHistory(); renderDictionary(); renderSettings(); }
// Launch at login lives in the Windows Run key; only the installed app can register itself.
function renderAutostart(status) {
  const toggle = $('#autostart-switch'); if (!toggle) return;
  toggle.disabled = !status.available; toggle.setAttribute('aria-checked', String(Boolean(status.enabled)));
  $('#autostart-desc').textContent = status.available ? 'Start quietly in the system tray.' : 'Available in the installed app (Start menu → Wispr Clone).';
}
async function refreshLists() {
  const [historyResult, dictResult, micResult, autostartResult] = await Promise.all([bridge.call('history_list'), bridge.call('dict_list'), bridge.call('mic_list'), bridge.call('autostart_get')]);
  if (autostartResult?.ok) renderAutostart(autostartResult.data);
  if (historyResult?.ok) state = { ...state, history: historyResult.data.runs ?? [] };
  if (dictResult?.ok) state = { ...state, dictionary: dictResult.data.entries ?? [] };
  if (micResult?.ok) { state = { ...state, microphones: micResult.data.devices ?? [] }; const select = $('#mic-select'); if (select) { select.innerHTML = state.microphones.map((device) => `<option value="${esc(device.device_id)}">${esc(device.name)}${device.is_default ? ' (default)' : ''}</option>`).join(''); select.value = micSelection(state.settings, state.microphones); } }
  render();
}
window.wisprEvent = (jsonText) => {
  try { const event = JSON.parse(jsonText); if (!event || typeof event !== 'object' || typeof event.name !== 'string') return; const accepted = acceptsEvent(state, event); state = applyEvent(state, event); if (event.name.startsWith('run:')) { if (!accepted) state.lastEvent = null; else state.lastEvent = event.name === 'run:state' ? event : null; currentRun = event.run_id; } if (event.name === 'audio:level' && event.run_id === null && $('#mic-test')?.dataset.running === 'true') lastMicLevelAt = Date.now(); if (event.name === 'history:changed') void refreshLists(); render(); }
  catch { /* Invalid event payloads are ignored. */ }
};

// Title bar: the page draws the caption; the host moves and sizes the native window.
$('.titlebar')?.addEventListener('mousedown', (event) => {
  if (event.button !== 0 || event.target.closest('button')) return;
  bridge.window(event.detail === 2 ? 'window_toggle_maximize' : 'window_drag');
});
$('.win-ctrl')?.addEventListener('click', (event) => { const button = event.target.closest('[data-window]'); if (button) bridge.window(button.dataset.window); });

$('#rec-btn')?.addEventListener('click', async () => {
  const active = run(); let result;
  if (active?.status === 'recording') result = await bridge.call('run_stop', { run_id: active.run_id });
  else { result = await bridge.call('run_start'); if (result?.ok) currentRun = result.data.run_id; }
  if (failed(result)) return; if (result?.data?.run_id) currentRun = result.data.run_id; render();
});
$('#dictate-cancel')?.addEventListener('click', async () => { const result = await bridge.call('run_cancel', { run_id: run()?.run_id }); if (!failed(result)) render(); });
document.addEventListener('click', async (event) => {
  const recover = event.target.closest('[data-recover]');
  if (recover) { if (recover.dataset.recover === 'cancel') { await $('#dictate-cancel').click(); return; } const active = run(); const result = await bridge.call('run_recover', { run_id: active.run_id, expected_version: active.version, action: recover.dataset.recover }); if (!failed(result)) { recover.remove(); render(); } return; }
  const copy = event.target.closest('[data-copy]'); if (copy) { const result = await bridge.call('history_copy', { run_id: copy.dataset.copy }); if (!failed(result)) toast('success', 'Copied', ''); return; }
  const del = event.target.closest('[data-delete]'); if (del) { const result = await bridge.call('history_delete', { run_id: del.dataset.delete }); if (!failed(result)) await refreshLists(); return; }
  const termEdit = event.target.closest('[data-edit-term]'); if (termEdit) { const item = state.dictionary.find((entry) => entry.id === Number(termEdit.dataset.editTerm)); if (!item) return; editingTermId = item.id; $('#term-input').value = item.spelling; $('#alias-input').value = (item.aliases ?? []).join(', '); $('#save-term').disabled = !termSaveEnabled(item.spelling); $('#term-modal').classList.add('is-open'); return; }
  const termDelete = event.target.closest('[data-delete-term]'); if (termDelete) { const result = await bridge.call('dict_delete', { id: Number(termDelete.dataset.deleteTerm) }); if (!failed(result)) await refreshLists(); }
});
$('#history-search')?.addEventListener('input', () => { const query = $('#history-search').value.toLowerCase(); $$('#history-list .item').forEach((item) => { item.hidden = !item.textContent.toLowerCase().includes(query); }); });
$('#history-filter')?.addEventListener('click', (event) => { const button = event.target.closest('[data-filter]'); if (!button) return; historyFilter = button.dataset.filter; $$('#history-filter [data-filter]').forEach((el) => el.setAttribute('aria-checked', String(el === button))); renderHistory(); });
$('#dict-search')?.addEventListener('input', renderDictionary);
$('#theme-seg')?.addEventListener('click', async (event) => { const button = event.target.closest('[data-theme-set]'); if (!button) return; const result = await bridge.call('settings_update', { patch: { theme: button.dataset.themeSet } }); if (failed(result)) return; state.settings = result.data; renderSettings(); });
$('#mode-seg')?.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-mode]'); if (!button) return;
  const result = await bridge.call('settings_update', { patch: { recording_mode: button.dataset.mode } });
  if (failed(result)) return; state.settings = result.data; renderSettings();
});
$('#shortcut-change')?.addEventListener('click', () => {
  const button = $('#shortcut-change'); const description = $('#shortcut-desc');
  button.textContent = 'Press keys… (Esc to cancel)'; button.classList.add('is-capturing');
  description.textContent = 'Press the shortcut you want to use.';
  const endCapture = (message = '') => {
    window.removeEventListener('keydown', onKeyDown, true);
    window.removeEventListener('blur', onBlur);
    button.textContent = 'Change'; button.classList.remove('is-capturing');
    description.textContent = message || 'Press Change, then the keys you want.';
  };
  const onBlur = () => endCapture();
  const onKeyDown = async (event) => {
    event.preventDefault();
    const modifiers = [event.ctrlKey && 'ctrl', event.altKey && 'alt', event.shiftKey && 'shift', event.metaKey && 'win'].filter(Boolean);
    if (['Control', 'Alt', 'Shift', 'Meta'].includes(event.key)) {
      description.textContent = modifiers.length ? `Pressed: ${modifiers.map((part) => part[0].toUpperCase() + part.slice(1)).join(' + ')}` : 'Press the shortcut you want to use.';
      return;
    }
    if (event.key === 'Escape' && modifiers.length === 0) { endCapture(); return; }
    const dictation_shortcut = toBinding(event);
    if (!dictation_shortcut) { endCapture('That key is not supported.'); return; }
    endCapture('Saving shortcut…');
    const result = await bridge.call('settings_update', { patch: { dictation_shortcut } });
    if (!result?.ok) { description.textContent = messageFor(result?.error); return; }
    state.settings = result.data; renderSettings(); description.textContent = 'Shortcut saved.';
  };
  window.addEventListener('keydown', onKeyDown, true);
  window.addEventListener('blur', onBlur);
});
$('#sound-switch')?.addEventListener('click', async () => { const result = await bridge.call('settings_update', { patch: { sound_cues: $('#sound-switch').getAttribute('aria-checked') !== 'true' } }); if (failed(result)) return; state.settings = result.data; renderSettings(); });
$('#cleanup-switch')?.addEventListener('click', async () => { const enabled = $('#cleanup-switch').getAttribute('aria-checked') !== 'true'; const result = await bridge.call('settings_update', { patch: { cleanup_enabled: enabled } }); if (failed(result)) return; state.settings = result.data; renderSettings(); });
$('#instructions')?.addEventListener('input', () => { $('#save-instructions').disabled = !instructionsDirty($('#instructions').value, state.settings.cleanup_instructions ?? ''); });
$('#save-instructions')?.addEventListener('click', async () => { const result = await bridge.call('settings_update', { patch: { cleanup_instructions: $('#instructions').value } }); if (failed(result)) return; state.settings = result.data; lastSavedInstructions = result.data.cleanup_instructions ?? ''; $('#save-instructions').disabled = true; $('#save-note').textContent = 'Saved'; });
$('#autostart-switch')?.addEventListener('click', async () => { const result = await bridge.call('autostart_set', { enabled: $('#autostart-switch').getAttribute('aria-checked') !== 'true' }); if (failed(result)) return; renderAutostart(result.data); });
$('#save-openrouter-key')?.addEventListener('click', async () => { const input = $('#openrouter-key'); const value = normalizeSecret(input.value); input.value = ''; const result = await bridge.call('secret_set', { name: 'openrouter_api_key', value }); if (failed(result)) return; state.secrets = { ...state.secrets, openrouter_api_key: result.data }; renderSettings(); });
$('#clear-openrouter-key')?.addEventListener('click', async () => { $('#openrouter-key').value = ''; const result = await bridge.call('secret_clear', { name: 'openrouter_api_key' }); if (failed(result)) return; state.secrets = { ...state.secrets, openrouter_api_key: result.data }; renderSettings(); });
$('#cleanup-provider')?.addEventListener('change', async (event) => {
  const select = event.target; select.disabled = true;
  try {
    const result = await bridge.call('settings_update', { patch: { cleanup_provider: select.value } });
    if (!failed(result)) { state.settings = result.data; modelCatalog = null; render(); void Promise.all([refreshCatalog(), refreshModelStatus()]); }
  } finally { select.disabled = false; select.value = cleanupProvider(); renderModels(); }
});
$('#save-nvidia-key')?.addEventListener('click', async () => {
  if (nvidiaKeyBusy) return;
  nvidiaKeyBusy = true;
  $('#save-nvidia-key').disabled = $('#clear-nvidia-key').disabled = true;
  const input = $('#nvidia-key'); const value = normalizeSecret(input.value); input.value = '';
  try {
    const result = await bridge.call('secret_set', { name: 'nvidia_api_key', value });
    if (failed(result)) return;
    state.secrets = { ...state.secrets, nvidia_api_key: result.data }; renderModels();
  } finally { nvidiaKeyBusy = false; $('#save-nvidia-key').disabled = $('#clear-nvidia-key').disabled = false; }
  await Promise.all([refreshCatalog(), refreshModelStatus()]);
});
$('#clear-nvidia-key')?.addEventListener('click', async () => {
  if (nvidiaKeyBusy) return;
  nvidiaKeyBusy = true;
  $('#save-nvidia-key').disabled = $('#clear-nvidia-key').disabled = true;
  $('#nvidia-key').value = '';
  try {
    const result = await bridge.call('secret_clear', { name: 'nvidia_api_key' });
    if (failed(result)) return;
    state.secrets = { ...state.secrets, nvidia_api_key: result.data }; renderModels();
  } finally { nvidiaKeyBusy = false; $('#save-nvidia-key').disabled = $('#clear-nvidia-key').disabled = false; }
  await Promise.all([refreshCatalog(), refreshModelStatus()]);
});
$('#refresh-nvidia-models')?.addEventListener('click', async () => {
  const button = $('#refresh-nvidia-models'); button.disabled = true;
  try { failed(await refreshCatalog()); } finally { button.disabled = false; }
});
$('#nvidia-fallback-list')?.addEventListener('input', (event) => {
  const input = event.target.closest('[data-fallback-index]'); if (!input) return;
  nvidiaFallbackDraft[Number(input.dataset.fallbackIndex)] = input.value;
  renderedNvidiaOrder = [...nvidiaFallbackDraft]; renderFallbackState();
});
$('#nvidia-fallback-list')?.addEventListener('click', (event) => {
  const button = event.target.closest('[data-fallback-action]'); if (!button || button.disabled) return;
  const index = Number(button.dataset.index); const action = button.dataset.fallbackAction;
  let focusIndex = index;
  if (action === 'remove') { if (nvidiaFallbackDraft.length <= 1) return; nvidiaFallbackDraft.splice(index, 1); focusIndex = Math.min(index, nvidiaFallbackDraft.length - 1); }
  else { const direction = action === 'up' ? -1 : 1; nvidiaFallbackDraft = moveModelOrder(nvidiaFallbackDraft, index, direction); focusIndex += direction; }
  renderFallbackOrder();
  const control = action === 'remove' ? $(`[data-fallback-index="${focusIndex}"]`) : $(`[data-fallback-action="${action}"][data-index="${focusIndex}"]`);
  (control?.disabled ? $(`[data-fallback-index="${focusIndex}"]`) : control)?.focus();
});
$('#add-nvidia-model')?.addEventListener('click', () => {
  if (nvidiaOrderSaving || (nvidiaFallbackDraft?.length ?? 0) >= 12) return;
  nvidiaFallbackDraft = [...(nvidiaFallbackDraft ?? []), '']; renderFallbackOrder();
  $(`[data-fallback-index="${nvidiaFallbackDraft.length - 1}"]`)?.focus();
});
$('#save-nvidia-models')?.addEventListener('click', async () => {
  const ids = normalizeModelOrder(nvidiaFallbackDraft ?? []);
  if (nvidiaOrderSaving || modelOrderIssue(ids)) return;
  nvidiaOrderSaving = true; renderFallbackState();
  try {
    const result = await bridge.call('settings_update', { patch: { nvidia_cleanup_model_ids: ids } });
    if (failed(result)) return;
    state.settings = result.data;
    nvidiaFallbackDraft = [...result.data.nvidia_cleanup_model_ids]; lastSavedNvidiaOrder = [...nvidiaFallbackDraft];
    renderModels(); void refreshModelStatus(); toast('success', 'Fallback order saved', 'Used from your next dictation.');
  } finally { nvidiaOrderSaving = false; renderFallbackState(); }
});
function setMicTestRunning(running) { const button = $('#mic-test'); button.dataset.running = String(running); button.innerHTML = `${icon(running ? 'stop' : 'mic')}${running ? 'Stop test' : 'Test microphone'}`; }
$('#mic-select')?.addEventListener('change', async () => { const microphone_id = $('#mic-select').value === '' ? null : $('#mic-select').value; const result = await bridge.call('settings_update', { patch: { microphone_id: microphone_id } }); if (failed(result)) return; state.settings = result.data; renderSettings(); });
$('#mic-test')?.addEventListener('click', async () => { const button = $('#mic-test'); const wasRunning = button.dataset.running === 'true'; const command = wasRunning ? 'mic_test_stop' : 'mic_test_start'; const result = await bridge.call(command, wasRunning ? {} : { device_id: micDeviceId($('#mic-select').value) }); if (failed(result)) return; const running = micTestRunningAfter(command, result, wasRunning); setMicTestRunning(running); if (running) lastMicLevelAt = Date.now(); });
// presentation-timer: return the microphone test button to idle after levels stop.
setInterval(() => { if ($('#mic-test')?.dataset.running === 'true' && lastMicLevelAt !== null && micTestEnded(lastMicLevelAt, Date.now())) setMicTestRunning(false); }, 500);
$('#delete-all')?.addEventListener('click', () => $('#delete-modal').classList.add('is-open'));
$('#confirm-delete')?.addEventListener('click', async () => { const result = await bridge.call('history_delete_all'); if (failed(result)) return; $('#delete-modal').classList.remove('is-open'); await refreshLists(); });
$('#term-input')?.addEventListener('input', () => { $('#save-term').disabled = !termSaveEnabled($('#term-input').value); });
$('#add-term')?.addEventListener('click', () => { editingTermId = null; $('#term-input').value = ''; $('#alias-input').value = ''; $('#save-term').disabled = true; $('#term-modal').classList.add('is-open'); });
$('#save-term')?.addEventListener('click', async () => { const entry = { spelling: $('#term-input').value.trim(), aliases: $('#alias-input').value.split(',').map((item) => item.trim()).filter(Boolean) }; const result = await bridge.call(editingTermId === null ? 'dict_add' : 'dict_update', editingTermId === null ? { entry } : { id: editingTermId, entry }); if (failed(result)) return; $('#term-modal').classList.remove('is-open'); await refreshLists(); });
$('#dict-import')?.addEventListener('click', () => { const input = document.createElement('input'); input.type = 'file'; input.accept = '.txt,.csv,text/plain,text/csv'; input.addEventListener('change', async () => { const file = input.files?.[0]; if (!file) return; const result = await bridge.call('dict_import', { text: await file.text() }); if (failed(result)) return; toast('success', 'Dictionary imported', `${result.data.added} added`); await refreshLists(); }); input.click(); });
$('#dict-export')?.addEventListener('click', async () => { const result = await bridge.call('dict_export'); if (failed(result)) return; let output = $('#dict-export-content'); if (!output) { output = document.createElement('textarea'); output.id = 'dict-export-content'; output.className = 'textarea'; output.setAttribute('aria-label', 'Dictionary export'); $('#page-dictionary .toolbar').after(output); } output.value = result.data.text ?? ''; output.hidden = false; output.focus(); output.select(); });
$$('[data-close]').forEach((button) => button.addEventListener('click', () => button.closest('.backdrop').classList.remove('is-open')));
$$('[data-goto]').forEach((button) => button.addEventListener('click', () => page(button.dataset.goto)));
$('#sidebar-toggle')?.addEventListener('click', () => { document.documentElement.dataset.sidebar = 'collapsed'; });
$('#side-logo')?.addEventListener('click', () => { const open = document.documentElement.dataset.sidebar === 'collapsed'; document.documentElement.dataset.sidebar = open ? '' : 'collapsed'; });
$$('[data-page]').forEach((button) => button.addEventListener('click', () => page(button.dataset.page)));
$$('[data-model]').forEach((card) => {
  const role = card.dataset.model === 'cleanup' ? 'cleanup' : 'stt';
  $('[data-test]', card)?.addEventListener('click', async () => { const model = state.models.find((item) => item.role === role); if (model) { const result = await bridge.call('models_test', { model_id: model.model_id, role }); if (failed(result)) return; toast(result.data.ready ? 'success' : 'warning', result.data.ready ? 'Model ready' : messageFor(result.data.error_code)); } });
  $('[data-select]', card)?.addEventListener('change', async (event) => {
    const result = await bridge.call('models_select', { model_id: event.target.value, role });
    if (!failed(result)) { state.settings = result.data.settings; state.models = result.data.models; toast('success', 'Model changed', role === 'cleanup' ? 'LM Studio is loading it if needed.' : 'Used from your next dictation.'); }
    event.target.blur(); render();
  });
});

document.addEventListener('keydown', (event) => {
  if (event.ctrlKey && !event.altKey && !event.shiftKey && event.code === 'KeyB') { event.preventDefault(); $('#side-logo')?.click(); }
  if (event.key === 'Escape') $$('.backdrop.is-open').forEach((modal) => modal.classList.remove('is-open'));
});

// Land on General; no page is marked active in the markup.
page('home');

(async () => {
  if (!bridge.available()) { render(); $('#title-status').innerHTML = '<span class="status-dot warning"></span>Not connected'; $('#rec-btn').disabled = true; await whenHostReady(window); }
  const result = await bridge.reconnect();
  if (failed(result)) return;
  state = { ...createStore(result.data), secrets: result.data.secrets }; currentRun = result.data.active_run_id; $('#title-status').innerHTML = '<span class="status-dot success"></span>Connected'; render();
  await refreshLists();
})();
