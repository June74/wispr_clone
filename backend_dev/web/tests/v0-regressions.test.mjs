import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const app = readFileSync(new URL('../app.js', import.meta.url), 'utf8');
const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const forms = await import('../lib/forms.js').catch(() => ({}));

test('T-WEB-023: term eligibility and Add/Edit modal wiring', () => {
  assert.equal(typeof forms.termSaveEnabled, 'function', 'termSaveEnabled must be exported');
  for (const value of ['', '  \n ', null, undefined, 3]) assert.equal(forms.termSaveEnabled(value), false);
  for (const value of ['Kubernetes', '  Kubernetes  ']) assert.equal(forms.termSaveEnabled(value), true);
  assert.match(app, /#term-input['"]\)\?\.addEventListener\(['"]input['"][\s\S]*?#save-term['"]\)\.disabled\s*=\s*!termSaveEnabled\(/);
  assert.match(app, /#add-term['"]\)\?\.addEventListener\(['"]click['"][\s\S]*?#save-term['"]\)\.disabled\s*=\s*true/);
  assert.match(app, /termEdit[\s\S]*?#term-input['"]\)\.value\s*=\s*item\.spelling[\s\S]*?#save-term['"]\)\.disabled\s*=\s*!?\s*(?:false|termSaveEnabled\()/);
  assert.match(html, /id="save-term"\s+disabled/);
});

test('T-WEB-024: instructions dirty state preserves edits and confirms save', () => {
  assert.equal(typeof forms.instructionsDirty, 'function', 'instructionsDirty must be exported');
  assert.equal(forms.instructionsDirty('', null), false);
  assert.equal(forms.instructionsDirty('', undefined), false);
  assert.equal(forms.instructionsDirty('saved', 'saved'), false);
  assert.equal(forms.instructionsDirty('changed', 'saved'), true);
  assert.equal(forms.instructionsDirty(' ', ''), true);
  assert.match(app, /#instructions['"]\)\?\.addEventListener\(['"]input['"][\s\S]*?#save-instructions['"]\)\.disabled\s*=\s*!instructionsDirty\(/);
  const settings = app.match(/function renderSettings\(\)\s*\{[\s\S]*?\n\}/)?.[0] ?? '';
  assert.match(settings, /instructionsDirty\(/, 'render must check whether the textarea has unsaved edits');
  assert.doesNotMatch(settings, /if\s*\(\$\(['"]#instructions['"]\)\)\s*\$\(['"]#instructions['"]\)\.value/, 'render must not overwrite every input');
  assert.match(app, /#save-instructions['"]\)\?\.addEventListener\(['"]click['"][\s\S]*?cleanup_instructions:\s*\$\(['"]#instructions['"]\)\.value[\s\S]*?#save-instructions['"]\)\.disabled\s*=\s*true[\s\S]*?#save-note['"]\)\.textContent\s*=\s*['"]Saved['"]/);
});

test('T-WEB-025: microphone IDs, selection, persistence and test payload', () => {
  assert.equal(typeof forms.micDeviceId, 'function', 'micDeviceId must be exported');
  assert.equal(forms.micDeviceId(''), null);
  assert.equal(forms.micDeviceId(null), null);
  assert.equal(forms.micDeviceId(undefined), null);
  assert.equal(forms.micDeviceId('0'), 0);
  assert.equal(forms.micDeviceId('3'), 3);
  assert.equal(typeof forms.micSelection, 'function', 'micSelection must be exported');
  const devices = [{ device_id: 0, is_default: true }, { device_id: 3, is_default: false }];
  assert.equal(forms.micSelection({ microphone_id: '3' }, devices), '3');
  assert.equal(forms.micSelection({ microphone_id: '9' }, devices), '0');
  assert.equal(forms.micSelection({}, [{ device_id: 3, is_default: false }]), '');
  assert.match(app, /#mic-select['"]\)\?\.addEventListener\(['"]change['"][\s\S]*?settings_update[\s\S]*?microphone_id:/);
  assert.match(app, /#mic-select['"]\)[\s\S]*?micSelection\(state\.settings,\s*state\.microphones\)/);
  assert.match(app, /mic_test_start[\s\S]*?device_id:\s*micDeviceId\(\$\(['"]#mic-select['"]\)\.value\)/);
});
