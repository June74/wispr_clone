import test from 'node:test';
import assert from 'node:assert/strict';
import { catalogNote, modelBadge, pickerOptions, sameModelOrder, normalizeModelOrder, modelOrderIssue, moveModelOrder, syncModelOrderDraft } from '../lib/models.js';

const catalog = {
  stt: { models: [{ model_id: 'openai/whisper-large-v3-turbo', display_name: 'Whisper' }, { model_id: 'deepgram/nova-3', display_name: 'Nova-3' }], error_code: null },
  cleanup: { models: [{ model_id: 'llama', display_name: 'Llama', loaded: true }, { model_id: 'qwen', display_name: 'Qwen', loaded: false }, { model_id: 'old', display_name: 'old', missing: true }], error_code: null },
};

test('T-WEB-021: picker lists live models, marks the current one and its state', () => {
  assert.deepEqual(pickerOptions('stt', catalog, 'deepgram/nova-3'), [
    { value: 'openai/whisper-large-v3-turbo', label: 'Whisper', selected: false },
    { value: 'deepgram/nova-3', label: 'Nova-3', selected: true },
  ]);
  assert.deepEqual(pickerOptions('cleanup', catalog, 'llama').map((option) => option.label), ['Llama', 'Qwen — not loaded', 'old — no longer offered']);
  // Before the catalog arrives the saved choice is still shown.
  assert.deepEqual(pickerOptions('cleanup', null, 'llama'), [{ value: 'llama', label: 'llama', selected: true }]);
});

test('T-WEB-021: notes and badges explain list and load state', () => {
  assert.equal(catalogNote('cleanup', catalog), '3 downloaded in LM Studio');
  assert.equal(catalogNote('stt', { stt: { models: [], error_code: 'stt_unavailable' } }), 'Couldn’t reach OpenRouter to list models.');
  assert.equal(catalogNote('stt', null), 'Loading the model list…');
  const messageFor = (code) => `msg:${code}`;
  assert.deepEqual(modelBadge({ ready: true }, messageFor), { tone: 'success', text: 'Ready' });
  assert.deepEqual(modelBadge({ ready: false, error_code: 'model_loading' }, messageFor), { tone: 'warning', text: 'msg:model_loading' });
  assert.deepEqual(modelBadge({ ready: false, error_code: 'cleanup_unavailable' }, messageFor), { tone: 'danger', text: 'msg:cleanup_unavailable' });
});

test('NVIDIA models use cloud catalog copy and key readiness', () => {
  const cloud = { cleanup: { provider: 'nvidia', models: [{ model_id: 'provider/model', display_name: 'Cloud model', loaded: false }, { model_id: 'old/model', missing: true }] } };
  assert.equal(catalogNote('cleanup', cloud), '1 available on NVIDIA');
  assert.equal(pickerOptions('cleanup', cloud, 'provider/model')[0].label, 'Cloud model');
  assert.equal(catalogNote('cleanup', { cleanup: { error_code: 'nvidia_api_key_missing' } }, 'nvidia'), 'Save an NVIDIA API key to list available models.');
  assert.equal(catalogNote('cleanup', { cleanup: { error_code: 'nvidia_api_key_invalid' } }, 'nvidia'), 'The NVIDIA API key was rejected. Check it in Models.');
  assert.equal(catalogNote('cleanup', { cleanup: { error_code: 'cleanup_timeout' } }, 'nvidia'), 'Couldn’t reach NVIDIA to list models.');
  assert.deepEqual(modelBadge({ ready: true }, (code) => code, 'nvidia'), { tone: 'success', text: 'Key saved' });
});

test('ordered fallback edits keep priority and reject unusable chains', () => {
  const saved = ['deepseek-ai/deepseek-v4.1-flash', 'z-ai/glm-5.3', 'moonshotai/kimi-k3'];
  const reordered = moveModelOrder(saved, 2, -1);
  assert.deepEqual(reordered, [saved[0], saved[2], saved[1]]);
  assert.deepEqual(saved, ['deepseek-ai/deepseek-v4.1-flash', 'z-ai/glm-5.3', 'moonshotai/kimi-k3']);
  assert.deepEqual(moveModelOrder(saved, 0, -1), saved);
  assert.deepEqual(moveModelOrder(saved, 2, 1), saved);
  assert.equal(sameModelOrder(saved, reordered), false);
  assert.deepEqual(normalizeModelOrder([' provider/model ']), ['provider/model']);
  assert.equal(modelOrderIssue(saved), '');
  assert.equal(modelOrderIssue([]), 'Add at least one model.');
  assert.equal(modelOrderIssue(['']), 'Enter a model ID for every step.');
  assert.equal(modelOrderIssue(['provider/model', ' provider/model ']), 'Each model can appear only once.');
  assert.equal(modelOrderIssue(['provider/model with spaces']), 'Model IDs cannot contain spaces.');
  assert.equal(modelOrderIssue(['just-model']), 'Use a model ID like vendor/model-name.');
  assert.equal(modelOrderIssue(['vendor/../../model']), 'Use a model ID like vendor/model-name.');
  assert.equal(modelOrderIssue(Array.from({ length: 13 }, (_, index) => `provider/model-${index}`)), 'Use at most 12 models.');
});

test('backend events preserve unsaved fallback edits but refresh a clean draft', () => {
  const saved = ['provider/first', 'provider/second'];
  assert.deepEqual(syncModelOrderDraft(null, null, saved), saved);
  const edited = ['provider/second', 'provider/first', 'provider/new'];
  assert.deepEqual(syncModelOrderDraft(edited, saved, saved), edited);
  const refreshed = ['provider/other'];
  assert.deepEqual(syncModelOrderDraft(saved, saved, refreshed), refreshed);
  assert.deepEqual(syncModelOrderDraft(edited, saved, refreshed), edited);
  const draft = syncModelOrderDraft(null, null, saved); draft.push('provider/new');
  assert.equal(saved.length, 2);
});
