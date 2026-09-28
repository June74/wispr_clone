import test from 'node:test';
import assert from 'node:assert/strict';
import { catalogNote, modelBadge, pickerOptions } from '../lib/models.js';

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
