import { createStore, applyEvent } from './lib/store.js';
import { hudState } from './lib/view.js';
import { createWaveform } from './waveform.js';
let state = createStore();
const dot = document.querySelector('#pill-dot');
const label = document.querySelector('#pill-label');
const wave = createWaveform(document.querySelector('#hud-wave'), () => '#fff');
function update() {
  const active = state.runs.find((run) => run.run_id === state.active_run_id) ?? state.runs[0];
  const status = active?.status ?? 'idle';
  const appearance = hudState(status);
  dot.className = `status-dot ${appearance.color === 'green' ? 'success live' : appearance.color === 'red' ? 'danger' : appearance.color === 'yellow' ? 'warning' : ''}`;
  label.textContent = status === 'recording' ? 'Listening' : status === 'processing' ? 'Working' : status === 'awaiting_destination' ? 'Waiting for destination' : status === 'awaiting_cleanup_choice' ? 'Needs attention' : status === 'error' || status === 'uncertain' ? 'Could not confirm' : 'Ready';
  const level = state.latestLevel;
  wave.update(level?.bands ?? [], status === 'recording' && level?.run_id === active?.run_id);
}
window.wisprEvent = (jsonText) => {
  try {
    const event = JSON.parse(jsonText);
    if (!event || typeof event !== 'object' || !['run:state', 'audio:level'].includes(event.name)) return;
    state = applyEvent(state, event); update();
  } catch { /* Invalid event payloads are ignored. */ }
};
