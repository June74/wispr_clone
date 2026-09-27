import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

test('T-UI-013: committed waveform fixture matches the real renderer', () => {
  const generator = fileURLToPath(new URL('./generate_waveform_golden.mjs', import.meta.url));
  const actual = execFileSync(process.execPath, [generator], { encoding: 'utf8' });
  const committed = readFileSync(new URL('../../tests/fixtures/waveform_golden.json', import.meta.url), 'utf8');
  assert.deepEqual(JSON.parse(committed), JSON.parse(actual));
  assert.equal(committed, actual);
});
