import { createWaveform, levelFromBands, resampleBands, targets } from '../waveform.js';

const input = [0.05, 0.18, 0.42, 0.76, 0.93, 0.67, 0.31, 0.12, 0.55, 0.81, 0.39, 0.08];
const wave = Array.from({ length: 128 }, (_, index) => Math.sin(index * 0.19));
const level = levelFromBands(input);
const bands = Array.from(resampleBands(input));
const pending = [];
let now = 0;
globalThis.performance = { now: () => now };
globalThis.matchMedia = () => ({ matches: false });
globalThis.requestAnimationFrame = callback => { pending.push(callback); return pending.length; };
const context = {
  setTransform() {}, clearRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {},
};
const canvas = { getContext: () => context };
const renderer = createWaveform(canvas);
renderer.update(input, true);
const frames = [];
for (let index = 0; index < 60; index++) {
  now += 32;
  const callback = pending.shift();
  if (!callback) throw new Error(`animation stopped at frame ${index}`);
  callback(now);
  frames.push(renderer.heights());
}
process.stdout.write(`${JSON.stringify({ input, wave, level, bands, targets: targets(level, bands, wave), frames }, null, 2)}\n`);
