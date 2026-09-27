import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const styles = readFileSync(new URL('../styles.css', import.meta.url), 'utf8');
const html = readFileSync(new URL('../hud.html', import.meta.url), 'utf8');

function declarations(selector) {
  const escape = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const rule = new RegExp(`(?:^|})\\s*${escape(selector)}\\s*\\{([^}]*)\\}`, 'm').exec(styles);
  assert.ok(rule, `missing ${selector} rule`);
  return new Map(rule[1].split(';').filter(Boolean).map(entry => {
    const colon = entry.indexOf(':');
    return [entry.slice(0, colon).trim(), entry.slice(colon + 1).trim()];
  }));
}

test('T-WEB-013: HUD pill fills its opaque window without translation or shadow', () => {
  const pill = declarations('.pill.hud-pill');
  assert.equal(pill.get('transform'), 'none');
  assert.equal(pill.get('margin'), '0');
  assert.equal(pill.get('box-shadow'), 'none');
  assert.equal(pill.get('width'), '100vw');
  assert.equal(pill.get('height'), '100vh');
  assert.equal(pill.get('padding'), '0 6px 0 16px');
  assert.equal(pill.get('border-radius'), '8px');
});

test('T-WEB-013: HUD root and label support the opaque, narrow pill', () => {
  assert.match(html, /<html\b[^>]*\bclass=["'][^"']*\bhud-root\b[^"']*["']/i);
  assert.equal(declarations('.hud-root, .hud-root body').get('background'), '#1b161d');
  const label = declarations('.hud-pill .pill-label');
  assert.equal(label.get('min-width'), '0');
  assert.equal(label.get('overflow'), 'hidden');
  assert.equal(label.get('text-overflow'), 'ellipsis');
  assert.equal(label.get('white-space'), 'nowrap');
});
