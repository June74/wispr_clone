import test from 'node:test';
import assert from 'node:assert/strict';
import {
  targets, resampleBands, levelFromBands, smoothLevel, smoothBands,
  N, W, H, SCALE, REST, X, OPACITY,
} from '../waveform.js';

// Independent copy of the approved waveform_final.js sampling and height formula.
const clamp = (value, low = 0, high = 1) => Math.max(low, Math.min(high, value));

function referenceInterpolate(values, position) {
  const at = clamp(position, 0, values.length - 1);
  const low = Math.floor(at);
  const high = Math.min(values.length - 1, low + 1);
  return values[low] + (values[high] - values[low]) * (at - low);
}

function referenceSmoothSample(values, position, radius) {
  let sum = 0;
  let weights = 0;
  for (let offset = -radius; offset <= radius; offset++) {
    const weight = radius + 1 - Math.abs(offset);
    sum += referenceInterpolate(values, position + offset) * weight;
    weights += weight;
  }
  return sum / weights;
}

function referenceTargets(level, bands, wave) {
  return Array.from({ length: 29 }, (_, index) => {
    const position = index / 28;
    const band = referenceSmoothSample(bands, position * 31, 1);
    const waveform = Math.abs(referenceSmoothSample(wave, position * 127, 2));
    return 2 + 57 * clamp(level) * (0.025 + 0.84 * band + 0.135 * waveform);
  });
}

function assertClose(actual, expected, label) {
  assert.ok(Math.abs(actual - expected) < 1e-6, `${label}: expected ${expected}, got ${actual}`);
}

test('T-WEB-009: geometry matches the approved Frequency Lanes renderer', () => {
  assert.deepEqual({ N, W, H, SCALE, REST }, { N: 29, W: 340, H: 72, SCALE: 2, REST: 2 });
  assert.equal(typeof X, 'function');
  assert.equal(OPACITY.length, 29);
  for (let index = 0; index < 29; index++) {
    assert.equal(X(index), 44 + 9 * index);
    assertClose(OPACITY[index], 0.30 + 0.55 * Math.sin(Math.PI * index / 28), `opacity ${index}`);
  }
});

test('T-WEB-009: targets preserve the reference sampling and height formula', () => {
  const cases = [
    { level: 0.4, bands: Array(32).fill(0.5), wave: Array(128).fill(0) },
    {
      level: 0.83,
      bands: Array.from({ length: 32 }, (_, index) => (index % 7) / 7),
      wave: Array.from({ length: 128 }, (_, index) => Math.sin(index * 0.19)),
    },
    {
      level: 1.7,
      bands: Array.from({ length: 32 }, (_, index) => index / 31),
      wave: Array.from({ length: 128 }, (_, index) => index / 127 - 0.5),
    },
  ];
  for (const [caseIndex, { level, bands, wave }] of cases.entries()) {
    const actual = targets(level, bands, wave);
    const expected = referenceTargets(level, bands, wave);
    assert.equal(actual.length, 29);
    for (let index = 0; index < 29; index++) {
      assertClose(actual[index], expected[index], `case ${caseIndex}, pillar ${index}`);
    }
  }
});

test('T-WEB-009: twelve bands resample linearly to 32, including ends and midpoints', () => {
  const bands = [0.25, 0.7, 0.1, 0.8, 0.3, 0.1, 0.9, 0.2, 0.6, 0.4, 0.15, 0.75];
  const sampled = resampleBands(bands);
  assert.equal(sampled.length, 32);
  assertClose(sampled[0], bands[0], 'first endpoint');
  assertClose(sampled[31], bands[11], 'last endpoint');
  for (const index of [1, 15, 16, 30]) {
    assertClose(sampled[index], referenceInterpolate(bands, index * 11 / 31), `resampled index ${index}`);
  }
  assert.equal(levelFromBands(bands), 0.9);
  assert.equal(levelFromBands([...bands.slice(0, 11), 1.4]), 1);
  assert.equal(levelFromBands(Array(12).fill(-0.2)), 0);
});

test('T-WEB-009: silence rests every pillar at exactly two pixels', () => {
  const silentBands = Array(12).fill(0);
  const level = levelFromBands(silentBands);
  assert.equal(level, 0);
  assert.deepEqual(targets(level, resampleBands(silentBands), Array(128).fill(0)), Array(29).fill(REST));
  assert.deepEqual(targets(0, Array(32).fill(1), Array(128).fill(1)), Array(29).fill(REST));
});

test('T-WEB-009b: level smoothing uses the reference attack and release times', () => {
  const dt = 0.016;
  for (const { current, target, time, label } of [
    { current: 0.2, target: 0.9, time: 0.045, label: 'rise' },
    { current: 0.9, target: 0.2, time: 0.150, label: 'fall' },
  ]) {
    const expected = current + (target - current) * (1 - Math.exp(-dt / time));
    assertClose(smoothLevel(current, target, dt), expected, label);
  }
});

test('T-WEB-009b: a silent target snaps a low level to exactly zero', () => {
  assert.equal(smoothLevel(0.007, 0, 0.016), 0);
  const current = 0.02;
  const dt = 0.016;
  const expected = current * Math.exp(-dt / 0.150);
  assertClose(smoothLevel(current, 0, dt), expected, 'level above snap threshold');
});

test('T-WEB-009b: bands converge with the reference 70 ms constant without mutating inputs', () => {
  const current = Float32Array.from({ length: 32 }, (_, index) => index / 64);
  const target = Float32Array.from({ length: 32 }, (_, index) => 1 - index / 64);
  const originalCurrent = current.slice();
  const originalTarget = target.slice();
  const dt = 0.016;
  const result = smoothBands(current, target, dt);
  const weight = 1 - Math.exp(-dt / 0.07);

  assert.ok(result instanceof Float32Array);
  assert.equal(result.length, 32);
  assert.notStrictEqual(result, current);
  for (let index = 0; index < 32; index++) {
    assertClose(result[index], current[index] + (target[index] - current[index]) * weight, `band ${index}`);
  }
  const next = smoothBands(result, target, dt);
  for (let index = 0; index < 32; index++) {
    assert.ok(Math.abs(target[index] - next[index]) < Math.abs(target[index] - result[index]), `band ${index} converges`);
  }
  assert.deepEqual(current, originalCurrent);
  assert.deepEqual(target, originalTarget);
});
