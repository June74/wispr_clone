import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

const web = new URL('../', import.meta.url);
const html = readFileSync(fileURLToPath(new URL('index.html', web)), 'utf8');
const app = readFileSync(fileURLToPath(new URL('app.js', web)), 'utf8');

test('T-WEB-017: the settings app has no inner pill or pill selectors', () => {
  for (const id of ['pill', 'pill-label', 'pill-dot', 'pill-meter', 'pill-timer', 'pill-cancel']) {
    assert.equal(new RegExp(`\\bid=["']${id}["']`).test(html), false, `index.html contains ${id}`);
    assert.equal(new RegExp(`#${id}\\b`).test(app), false, `app.js selects ${id}`);
  }
  assert.match(html, /id=["']dictate-cancel["']/);
});
