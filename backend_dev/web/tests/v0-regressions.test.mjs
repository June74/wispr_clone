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
