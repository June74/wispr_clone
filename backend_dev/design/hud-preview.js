import { hudState } from '../web/lib/view.js';
import { createWaveform } from '../web/waveform.js';

const LABELS = {
  recording: 'Listening', processing: 'Working', awaiting_destination: 'Waiting for destination',
  awaiting_cleanup_choice: 'Needs attention', error: 'Could not confirm', idle: 'Ready',
};
const SLIDERS = [
  ['height', 'Height', 20, 56, 1], ['padL', 'Padding left', 4, 24, 1], ['padR', 'Padding right', 0, 24, 1],
  ['gap', 'Gap', 2, 16, 1], ['font', 'Label size', 9, 14, 0.5], ['weight', 'Label weight', 400, 700, 100],
  ['dot', 'Dot size', 4, 10, 1], ['waveW', 'Wave width', 24, 120, 2], ['waveH', 'Wave height', 10, 36, 1],
  ['radius', 'Corner radius', 4, 30, 1],
  ['width', 'Window width (when not auto)', 60, 320, 2],
];
const PRESETS = {
  current: { height: 44, padL: 16, padR: 6, gap: 12, font: 12, weight: 500, dot: 8, waveW: 88, waveH: 28, width: 272, hideListeningLabel: false, radius: 8 },
  compact: { height: 32, padL: 12, padR: 8, gap: 8, font: 11, weight: 500, dot: 6, waveW: 56, waveH: 18, width: 200, hideListeningLabel: false, radius: 8 },
  mini: { height: 26, padL: 10, padR: 8, gap: 6, font: 10.5, weight: 500, dot: 6, waveW: 44, waveH: 14, width: 120, hideListeningLabel: true, radius: 8 },
};
const $ = (selector) => document.querySelector(selector);
const saved = JSON.parse(localStorage.getItem('hud-preview') || 'null');
let config = { ...PRESETS.compact, radius: 8, ...(saved ?? {}) };

function hud(status) {
  const pill = document.createElement('div');
  pill.className = 'pill is-open hud-pill pv-hud';
  pill.innerHTML = '<span class="status-dot"></span><span class="pill-label"></span><canvas class="hud-wave" aria-hidden="true"></canvas>';
  const wave = createWaveform(pill.querySelector('canvas'), () => '#fff');
  const set = (next) => {
    const color = hudState(next).color;
    pill.querySelector('.status-dot').className = `status-dot ${color === 'green' ? 'success live' : color === 'red' ? 'danger' : color === 'yellow' ? 'warning' : ''}`;
    pill.querySelector('.pill-label').textContent = LABELS[next];
    pill.classList.toggle('is-wave-only', next === 'recording' && config.hideListeningLabel);
    pill.dataset.status = next;
  };
  set(status);
  return { pill, wave, set };
}

// Build controls
const sliders = $('#sliders');
for (const [key, name, min, max, step] of SLIDERS) {
  const label = document.createElement('label');
  label.innerHTML = `${name}<span class="pv-row"><input type="range" min="${min}" max="${max}" step="${step}" data-key="${key}"><output></output></span>`;
  sliders.append(label);
}

const main = hud('recording');
$('#main-window').append(main.pill);
const all = Object.keys(LABELS).map((status) => {
  const frame = document.createElement('div');
  frame.className = 'pv-window';
  const item = hud(status);
  frame.append(item.pill);
  $('#all').append(frame);
  return { frame, ...item };
});
const measure = document.createElement('div');
measure.className = 'pv-measure';
document.body.append(measure);

function naturalWidth() {
  measure.replaceChildren();
  let widest = 0;
  for (const status of Object.keys(LABELS)) {
    const probe = hud(status);
    measure.append(probe.pill);
    widest = Math.max(widest, probe.pill.getBoundingClientRect().width);
  }
  measure.replaceChildren();
  return Math.ceil(widest);
}

function apply() {
  const root = document.documentElement.style;
  root.setProperty('--gap', `${config.gap}px`);
  root.setProperty('--pad-l', `${config.padL}px`);
  root.setProperty('--pad-r', `${config.padR}px`);
  root.setProperty('--font', `${config.font}px`);
  root.setProperty('--weight', String(config.weight));
  root.setProperty('--dot', `${config.dot}px`);
  root.setProperty('--wave-w', `${config.waveW}px`);
  root.setProperty('--wave-h', `${config.waveH}px`);
  root.setProperty('--radius', `${Math.min(config.radius, config.height / 2)}px`);
  const width = $('#autoWidth').checked ? naturalWidth() : config.width;
  config.windowWidth = width;
  const zoom = Number($('#zoom').value);
  const size = (el, z) => { el.style.width = `${width}px`; el.style.height = `${config.height}px`; el.style.zoom = String(z); };
  size($('#main-window'), zoom);
  for (const item of all) { size(item.frame, 1); item.set(item.pill.dataset.status); }
  main.set($('#status').value);
  for (const input of sliders.querySelectorAll('input')) {
    input.value = config[input.dataset.key];
    input.nextElementSibling.textContent = config[input.dataset.key];
    input.disabled = input.dataset.key === 'width' && $('#autoWidth').checked;
  }
  $('#hideListeningLabel').checked = config.hideListeningLabel;
  $('#size').textContent = `Native window: ${width} × ${config.height} px (shipped: 272 × 44)`;
  $('#out').value = JSON.stringify({ hud: {
    window: [width, config.height], padding: [config.padL, config.padR], gap: config.gap,
    label: { size: config.font, weight: config.weight, hideWhileListening: config.hideListeningLabel },
    dot: config.dot, wave: [config.waveW, config.waveH], radius: Math.min(config.radius, config.height / 2),
  } }, null, 1);
  localStorage.setItem('hud-preview', JSON.stringify(config));
  for (const button of document.querySelectorAll('[data-preset]')) {
    const preset = PRESETS[button.dataset.preset];
    button.setAttribute('aria-pressed', String(Object.keys(preset).every((key) => key === 'width' || preset[key] === config[key])));
  }
}

sliders.addEventListener('input', (event) => { config[event.target.dataset.key] = Number(event.target.value); apply(); });
for (const button of document.querySelectorAll('[data-preset]')) button.addEventListener('click', () => { config = { ...PRESETS[button.dataset.preset] }; apply(); });
$('#status').addEventListener('change', apply);
$('#zoom').addEventListener('change', apply);
$('#autoWidth').addEventListener('change', apply);
$('#hideListeningLabel').addEventListener('change', (event) => { config.hideListeningLabel = event.target.checked; apply(); });
$('#lightDesk').addEventListener('change', (event) => { $('#stage').classList.toggle('is-light', event.target.checked); $('#all').classList.toggle('is-light', event.target.checked); });
$('#copy').addEventListener('click', async () => { await navigator.clipboard?.writeText($('#out').value).catch(() => {}); $('#out').select(); $('#copy').textContent = 'Copied'; setTimeout(() => { $('#copy').textContent = 'Copy settings'; }, 1200); });

// Simulated speech levels (12 bands) for every "Listening" HUD.
let t = 0;
setInterval(() => {
  t += 0.05;
  const envelope = Math.max(0, Math.sin(t * 1.3) * 0.6 + Math.sin(t * 3.1) * 0.3 + 0.25);
  const bands = Array.from({ length: 12 }, (_, i) => Math.min(1, envelope * (0.35 + 0.65 * Math.abs(Math.sin(t * 2 + i * 0.7)))));
  for (const item of [main, ...all]) item.wave.update(bands, item.pill.dataset.status === 'recording');
}, 50);

apply();
