import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { normalizeSecret } from '../lib/secrets.js';

test('T-WEB-012: pasted key boundaries are trimmed before Save', () => {
  const fakeKey = 'sk-or-v1-test-web';
  for (const boundary of [' ', '\n', '\r\n', '\u00a0', '\u200b', '\u200c', '\u200d', '\u2060', '\ufeff']) {
    assert.equal(normalizeSecret(boundary + fakeKey + boundary), fakeKey);
  }
  assert.equal(normalizeSecret(fakeKey + ' ' + fakeKey), fakeKey + ' ' + fakeKey);
  for (const interior of ['\u200b', '\u200c', '\u200d', '\u2060', '\ufeff']) {
    assert.equal(normalizeSecret(fakeKey + interior + fakeKey), fakeKey + interior + fakeKey);
  }
  assert.equal(normalizeSecret(' \r\n\u00a0\u200b\ufeff'), '');

  const app = readFileSync(new URL('../app.js', import.meta.url), 'utf8');
  assert.match(app, /import\s*\{\s*normalizeSecret\s*\}\s*from\s*['"]\.\/lib\/secrets\.js['"]/);
  const saveHandler = app.split("$('#save-openrouter-key')?.addEventListener('click'")[1]
    ?.split("$('#clear-openrouter-key')?.addEventListener('click'")[0] ?? '';
  assert.ok(saveHandler, 'Save handler is missing');
  const normalizeAt = saveHandler.indexOf('normalizeSecret(input.value)');
  const clearAt = saveHandler.indexOf("input.value = ''");
  const sendAt = saveHandler.indexOf("bridge.call('secret_set'");
  assert.ok(normalizeAt >= 0 && normalizeAt < clearAt && clearAt < sendAt,
    'Save must normalize the key, clear the input, then send it');
});

test('NVIDIA key save also clears the normalized input before sending it', () => {
  const app = readFileSync(new URL('../app.js', import.meta.url), 'utf8');
  const handler = app.split("$('#save-nvidia-key')?.addEventListener('click'")[1]?.split("$('#clear-nvidia-key')?.addEventListener('click'")[0] ?? '';
  assert.ok(handler, 'NVIDIA Save handler is missing');
  const normalizeAt = handler.indexOf('normalizeSecret(input.value)');
  const clearAt = handler.indexOf("input.value = ''");
  const sendAt = handler.indexOf("bridge.call('secret_set'");
  assert.ok(normalizeAt >= 0 && normalizeAt < clearAt && clearAt < sendAt);
  assert.match(handler, /name: 'nvidia_api_key'/);
});
