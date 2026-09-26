import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createContext, runInContext, runInNewContext } from 'node:vm';
import { createStore, applyEvent } from '../lib/store.js';

const source = readFileSync(new URL('../app.js', import.meta.url), 'utf8');
const definition = source.match(/^const esc = .*;$/m)?.[0];

test('HTML escaping protects text and double-quoted attributes', () => {
  assert.ok(definition, 'app.js must define esc()');
  const escape = runInNewContext(`${definition}\nesc`, {});
  assert.equal(
    escape('&< >"\'`'),
    '&amp;&lt; &gt;&quot;&#39;`',
  );
  assert.equal(escape('" onmouseover="alert(1)&x=<img>'),
    '&quot; onmouseover=&quot;alert(1)&amp;x=&lt;img&gt;');
  assert.equal(escape(null), '');
});

test('a stale done event cannot trigger the inserted toast in app wiring', () => {
  const handler = source.match(/window\.wisprEvent = \(jsonText\) => \{[\s\S]*?\n\};/)?.[0];
  assert.ok(handler, 'app.js must register the event handler');
  const context = createContext({
    window: {},
    JSON,
    applyEvent,
    render() {},
    refreshLists() {},
    initialState: createStore({ runs: [{ run_id: 'r', version: 5, status: 'processing' }] }),
  });
  runInContext(`let state = initialState; let currentRun = null; ${handler}`, context);
  context.window.wisprEvent(JSON.stringify({
    name: 'run:state', run_id: 'r', version: 4, status: 'done',
  }));
  assert.equal(runInContext('state.lastEvent', context), undefined);
});
