import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createBridge } from '../lib/bridge.js';
import { messages } from '../lib/messages.js';

const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const app = readFileSync(new URL('../app.js', import.meta.url), 'utf8');

test('T-WEB-010: Models offers a password field and key actions', () => {
  const models = html.split('id="page-models"')[1]?.split('id="page-privacy"')[0] ?? '';
  assert.ok(models.includes('OpenRouter API key'), 'key label is missing');
  assert.ok(/<input\b[^>]*type="password"[^>]*autocomplete="off"/.test(models), 'password field is missing');
  assert.ok(models.includes('Save'), 'Save is missing');
  assert.ok(models.includes('Clear'), 'Clear is missing');
  assert.ok((html + app).includes('Key saved'), 'saved status is missing');
  assert.ok((html + app).includes('No key saved'), 'empty status is missing');
  assert.match(app, /secret_set/);
  assert.match(app, /secret_clear/);
  assert.doesNotMatch(app, /innerHTML\s*=\s*[^;]*openrouter_api_key/);
  assert.doesNotMatch(app, /textContent\s*=\s*[^;]*openrouter_api_key/);
});

test('T-WEB-010: secret commands carry session and deadline metadata', async () => {
  const calls = [];
  const bridge = createBridge(async (name, payload) => {
    calls.push({ name, payload });
    if (name === 'state_get') return { ok: true, data: { session_token: 'test-session' } };
    return { ok: true, data: { configured: true } };
  }, { now: () => 1000 });
  await bridge.reconnect();
  await bridge.call('secret_set', { name: 'openrouter_api_key', value: 'sk-or-v1-test-web' });
  await bridge.call('secret_clear', { name: 'openrouter_api_key' });
  assert.deepEqual(calls.slice(1).map(({ name, payload }) => ({ name, deadline: payload.deadline, token: payload.session_token })), [
    { name: 'secret_set', deadline: 11, token: 'test-session' },
    { name: 'secret_clear', deadline: 11, token: 'test-session' },
  ]);
});

test('T-WEB-010: messages and privacy text describe cloud transcription', () => {
  assert.equal(messages.api_key_missing, 'Add your OpenRouter API key in Models to enable dictation.');
  assert.equal(messages.api_key_invalid, 'The OpenRouter API key was rejected. Check it in Models.');
  const privacy = html.split('id="page-privacy"')[1]?.split('id="page-')[0] ?? '';
  assert.ok(privacy.includes('Your audio is sent to OpenRouter and transcribed by DeepInfra (Whisper Large v3 Turbo). Transcripts stay on this PC.'), 'privacy copy is missing');
  assert.doesNotMatch(html, /nothing leaves this device/i);
  assert.doesNotMatch(html, /Everything stays on this computer/i);
  assert.doesNotMatch(html, /Audio is never saved/i);
  assert.match(app, /Whisper Large v3 Turbo \(DeepInfra\)/);
});

test('T-WEB-011: Privacy page does not claim local-only mode is active by default', () => {
  const privacy = html.split('id="page-privacy"')[1]?.split('id="page-styleguide"')[0] ?? '';
  const localOnlyRow = privacy.split('Local-only mode')[1]?.split('</button>')[0] ?? '';
  assert.ok(localOnlyRow, 'local-only privacy row is missing');
  assert.match(localOnlyRow, /aria-checked="false"/);
});
