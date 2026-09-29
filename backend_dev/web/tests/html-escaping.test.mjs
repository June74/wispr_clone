import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createContext, runInContext, runInNewContext } from 'node:vm';
import { createStore, applyEvent, acceptsEvent } from '../lib/store.js';

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

test('T-WEB-030: a stale done event cannot trigger the inserted toast in app wiring', () => {
  const handler = source.match(/window\.wisprEvent = \(jsonText\) => \{[\s\S]*?\n\};/)?.[0];
  assert.ok(handler, 'app.js must register the event handler');
  const context = createContext({
    window: {},
    JSON,
    applyEvent,
    acceptsEvent,
    render() {},
    refreshLists() {},
    initialState: createStore({ runs: [{ run_id: 'r', version: 5, status: 'processing' }] }),
  });
  runInContext(`let state = initialState; let currentRun = null; ${handler}`, context);
  context.window.wisprEvent(JSON.stringify({
    name: 'run:state', run_id: 'r', version: 4, status: 'done',
  }));
  assert.equal(runInContext('state.lastEvent', context), null);
  context.window.wisprEvent(JSON.stringify({
    name: 'run:state', run_id: 'r', version: 6, status: 'done',
  }));
  assert.equal(runInContext('state.lastEvent?.status', context), 'done');
  assert.equal(runInContext('state.lastEvent?.version', context), 6);
});
