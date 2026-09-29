/* Frequency Lanes on Quiet Pillars — backend-driven waveform renderer. */
export const N = 29;
export const W = 340;
export const H = 72;
export const SCALE = 2;
const CENTER = 36;
export const REST = 2;

const clamp = (value, low = 0, high = 1) => Math.max(low, Math.min(high, value));

function interpolate(values, position) {
  const at = clamp(position, 0, values.length - 1);
  const low = Math.floor(at);
  const high = Math.min(values.length - 1, low + 1);
  return values[low] + (values[high] - values[low]) * (at - low);
}

function smoothSample(values, position, radius) {
  let sum = 0;
  let weights = 0;
  for (let offset = -radius; offset <= radius; offset++) {
    const weight = radius + 1 - Math.abs(offset);
    sum += interpolate(values, position + offset) * weight;
    weights += weight;
  }
  return sum / weights;
}

export function targets(level, bands, wave) {
  return Array.from({ length: N }, (_, index) => {
    const position = index / 28;
    const band = smoothSample(bands, position * 31, 1);
    const waveform = Math.abs(smoothSample(wave, position * 127, 2));
    return REST + 57 * clamp(level) * (0.025 + 0.84 * band + 0.135 * waveform);
  });
}

export function resampleBands(bands) {
  const input = Array.from({ length: 12 }, (_, index) => clamp(Number(bands[index]) || 0));
  return Float32Array.from({ length: 32 }, (_, index) => interpolate(input, index * 11 / 31));
}

export function levelFromBands(bands) {
  return clamp(Math.max(0, ...Array.from({ length: 12 }, (_, index) => Number(bands[index]) || 0)));
}

export const X = (index) => 44 + 9 * index;
export const OPACITY = Array.from({ length: N }, (_, index) => 0.30 + 0.55 * Math.sin(Math.PI * index / 28));

const ZERO_WAVE = new Float32Array(128);
const REDUCED_TRACE = Float32Array.from({ length: 128 }, (_, index) => Math.sin(index * 0.18) * 0.7);

export function smoothLevel(current, target, dt) {
  let next = current + (target - current) * (1 - Math.exp(-dt / (target > current ? 0.045 : 0.150)));
  if (target === 0 && next < 0.008) next = 0;
  return next;
}

export function smoothBands(current32, target32, dt) {
  return Float32Array.from(current32, (current, index) =>
    current + (target32[index] - current) * (1 - Math.exp(-dt / 0.07)));
}

export function createWaveform(canvas, color = () => '#745689') {
  canvas.width = W * SCALE;
  canvas.height = H * SCALE;
  const context = canvas.getContext('2d');
  context.setTransform(SCALE, 0, 0, SCALE, 0, 0);
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');

  let mode = 'idle';
  let level = 0;
  let bands = new Float32Array(32);
  let targetLevel = 0;
  let targetBands = new Float32Array(32);
  const heights = new Array(N).fill(REST);
  let frame = 0;
  let lastTick = 0;
  let lastPaint = 0;

  function paint() {
    context.clearRect(0, 0, W, H);
    context.strokeStyle = color();
    context.lineCap = 'round';
    context.lineWidth = 3;
    for (let index = 0; index < N; index++) {
      context.globalAlpha = OPACITY[index];
      context.beginPath();
      context.moveTo(X(index), CENTER - heights[index] / 2);
      context.lineTo(X(index), CENTER + heights[index] / 2);
      context.stroke();
    }
    context.globalAlpha = 1;
  }

  function tick(now) {
    const dt = Math.min(0.08, (now - lastTick) / 1000 || 0.016);
    lastTick = now;
    level = smoothLevel(level, targetLevel, dt);
    bands = smoothBands(bands, targetBands, dt);

    const interval = reduced.matches ? 250 : 32;
    if (now - lastPaint >= interval) {
      const paintDt = Math.min(0.15, Math.max(0.008, (now - lastPaint) / 1000));
      lastPaint = now;
      const desired = targets(level, bands, reduced.matches ? REDUCED_TRACE : ZERO_WAVE);
      const immediate = level === 0 || reduced.matches;
      for (let index = 0; index < N; index++) {
        const easing = immediate ? 1 : 1 - Math.exp(-paintDt / (desired[index] > heights[index] ? 0.045 : 0.110));
        heights[index] += (desired[index] - heights[index]) * easing;
      }
      paint();
    }
    if (mode === 'idle' && level === 0 && heights.every((height) => height === REST)) {
      frame = 0;
      return;
    }
    frame = requestAnimationFrame(tick);
  }

  function run() {
    if (!frame) {
      lastTick = lastPaint = performance.now();
      frame = requestAnimationFrame(tick);
    }
  }

  function update(levelBands, running) {
    const valid = Array.isArray(levelBands) || ArrayBuffer.isView(levelBands);
    const input = valid && levelBands.length === 12 ? levelBands : Array(12).fill(0);
    targetBands = resampleBands(input);
    targetLevel = levelFromBands(input);
    mode = running ? 'active' : 'idle';
    run();
  }

  paint();
  return { update, heights: () => heights.slice() };
}
