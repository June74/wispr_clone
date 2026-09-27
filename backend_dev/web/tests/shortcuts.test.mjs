import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { toBinding, formatBinding } from '../lib/shortcuts.js';

const app = readFileSync(new URL('../app.js', import.meta.url), 'utf8');
const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');

function keyEvent(key, code = key, modifiers = {}) {
  return {
    key, code,
    ctrlKey: false, altKey: false, shiftKey: false, metaKey: false,
    ...modifiers,
  };
}

test('T-WEB-014: key events become canonical bindings', () => {
  assert.equal(toBinding(keyEvent('F3')), 'f3');
  assert.equal(toBinding(keyEvent(' ', 'Space', { ctrlKey: true, shiftKey: true })), 'ctrl+shift+space');
  assert.equal(toBinding(keyEvent('d', 'KeyD', { metaKey: true })), 'win+d');
  assert.equal(toBinding(keyEvent('5', 'Digit5', { altKey: true })), 'alt+5');
  assert.equal(toBinding(keyEvent('PageUp')), 'page_up');
  assert.equal(toBinding(keyEvent('Control', 'ControlLeft', { ctrlKey: true })), null);
  assert.equal(toBinding(keyEvent('Unidentified')), null);
  assert.equal(toBinding(keyEvent('F25')), null);
});

test('T-WEB-015: bindings have readable labels', () => {
  assert.equal(formatBinding('ctrl+shift+space'), 'Ctrl + Shift + Space');
  assert.equal(formatBinding('f3'), 'F3');
  assert.equal(formatBinding('win+d'), 'Win + D');
});

test('T-WEB-016: settings UI wires recording mode and shortcut capture', () => {
  assert.match(app, /#mode-seg[^\n]*addEventListener\(['"]click['"]/);
  assert.match(app, /settings_update[\s\S]*?patch:\s*\{\s*recording_mode\b/);
  assert.match(app, /#shortcut-change[^\n]*addEventListener\(['"]click['"]/);
  assert.match(app, /toBinding\(event\)/);
  assert.match(app, /settings_update[\s\S]*?patch:\s*\{\s*dictation_shortcut\b/);
  assert.match(html, /<kbd\b[^>]*id=["']shortcut-current["']/);
  assert.match(html, /<button\b[^>]*id=["']shortcut-change["']/);
  assert.doesNotMatch(html, /<select\b[^>]*id=["']shortcut-select["']/);
});
