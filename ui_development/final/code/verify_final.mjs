// Drives the demo in headless Chromium, asserts key flows, saves screenshots.
// Reuses the Playwright + browser already installed in ui_development/.tools_codex (no new install).
// Run: node final/code/verify_final.mjs   (from ui_development/)
// Test captures go to a temp folder; the curated images live in ../screenshots.
import assert from 'node:assert/strict';
import path from 'node:path';
import os from 'node:os';
import { mkdirSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
const here = path.dirname(fileURLToPath(import.meta.url));
const tools = path.join(here, '../../.tools_codex');
const shotsDir = path.join(os.tmpdir(), 'wispr-final-verify');
mkdirSync(shotsDir, { recursive: true });
process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(tools, 'browsers');
const { chromium } = await import(pathToFileURL(path.join(tools, 'node_modules/playwright/index.mjs')).href);
const browser = await chromium.launch({ headless: true, env: { ...process.env, LD_LIBRARY_PATH: path.join(tools, 'libs/usr/lib/x86_64-linux-gnu') } });
const page = await (await browser.newContext({ viewport: { width: 1360, height: 900 } })).newPage();
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
const url = (q) => pathToFileURL(path.join(here, 'index_final.html')).href + '?' + q;
const shot = async (name, full = false) => { await page.waitForTimeout(450); await page.screenshot({ path: path.join(shotsDir, `${name}.png`), fullPage: full }); };
const pass = (m) => console.log('PASS', m);

try {
  for (const theme of ['light', 'dark']) {
    await page.goto(url(`page=home&theme=${theme}`));
    await page.evaluate(() => document.fonts.ready);
    assert.ok(await page.evaluate(() => document.fonts.check('13px Geist')), 'Geist loaded');
    await shot(`home-${theme}`);
    for (const p of ['general', 'recording', 'models', 'cleanup', 'dictionary', 'privacy']) { await page.goto(url(`page=${p}&theme=${theme}`)); await shot(`${p}-${theme}`); }
  }
  pass('All views render in both themes with Geist');

  // Single sidebar: App / Voice / Data, no rail, no theme button
  await page.goto(url('page=home&theme=light'));
  assert.equal(await page.locator('.rail, #theme-toggle').count(), 0);
  await page.locator('#sidebar-toggle').isVisible();
  assert.deepEqual(await page.locator('.nav-label').allInnerTexts(), ['App', 'Voice', 'Data']);
  assert.deepEqual((await page.locator('.nav-item[data-page]').allInnerTexts()).map((t) => t.replace(/\d+$/, '').trim()),
    ['General', 'System', 'Recording', 'Models', 'Text cleanup', 'Dictionary', 'Privacy & data', 'History']);
  await page.click('.nav-item[data-page="general"]');
  assert.equal(await page.locator('#page-general h1').innerText(), 'System');
  await page.click('#theme-seg [data-theme-set="dark"]');
  assert.equal(await page.getAttribute('html', 'data-theme'), 'dark');
  await page.click('#theme-seg [data-theme-set="light"]');
  await page.click('.nav-item[data-page="history"]');
  assert.equal(await page.locator('#crumb').innerText(), 'Data · History');
  await shot('history-light');
  pass('Single sidebar with App/Voice/Data; theme lives in System');

  // Sidebar: collapse to icon strip, tooltip on hover, reopen via whitespace / logo / Ctrl+B, persisted
  await page.goto(url('page=home&theme=light'));
  await shot('sidebar-open-light');
  const ys = () => page.$$eval('#sidebar button[data-tip]', (els) => els.map((e) => Math.round(e.getBoundingClientRect().top * 2) / 2));
  const openYs = await ys();
  await page.click('#sidebar-toggle');
  await page.waitForTimeout(450);
  assert.equal(await page.getAttribute('html', 'data-sidebar'), 'collapsed');
  assert.deepEqual(await ys(), openYs, 'icons keep the same vertical position in both states');
  const w = (await page.locator('.side-card').boundingBox()).width;
  assert.ok(w > 45 && w < 60, `strip width ${w}`);
  await page.hover('.nav-item[data-page="recording"]');
  await page.waitForTimeout(250);
  assert.equal(await page.locator('#tip').innerText(), 'Recording');
  assert.ok(await page.locator('#tip').evaluate((t) => t.classList.contains('is-on')));
  await shot('sidebar-collapsed-tooltip-light');
  await page.hover('#side-logo'); await page.waitForTimeout(250);
  assert.ok(!(await page.locator('#tip').evaluate((t) => t.classList.contains('is-on'))), 'no popup on logo hover');
  await page.click('.nav-item[data-page="models"]');           // icons still navigate while collapsed
  assert.equal(await page.getAttribute('html', 'data-sidebar'), 'collapsed');
  assert.equal(await page.locator('#crumb').innerText(), 'Voice · Models');
  await page.reload(); await page.waitForTimeout(300);
  assert.equal(await page.getAttribute('html', 'data-sidebar'), 'collapsed', 'persists');
  // Divider rows in the collapsed strip are NOT triggers; no divider above General
  await page.waitForTimeout(400);
  for (const label of await page.locator('.nav-label').all()) {     // includes the line between search and General
    await label.click();
    assert.equal(await page.getAttribute('html', 'data-sidebar'), 'collapsed', 'divider click must not expand');
  }
  // Header and search row (incl. the lines around the search icon) are not triggers
  const qs = await page.locator('#quick-search').boundingBox();
  for (const y of [qs.y - 5, qs.y + qs.height + 5]) {          // padding just above/below search
    await page.mouse.click(qs.x + qs.width / 2, y);
    assert.equal(await page.getAttribute('html', 'data-sidebar'), 'collapsed', `search-row padding at y=${y} must not expand`);
  }
  const head = await page.locator('.side-head').boundingBox();
  await page.mouse.click(head.x + head.width / 2, head.y + head.height - 3);
  assert.equal(await page.getAttribute('html', 'data-sidebar'), 'collapsed', 'header must not expand');

  // Even rhythm: every icon is the same distance from the line above/below it
  await page.waitForTimeout(400);
  const gaps = await page.evaluate(() => {
    const r = (el) => el.getBoundingClientRect();
    const out = [];
    const search = r(document.querySelector('#quick-search'));
    out.push(['head line → search', search.top - r(document.querySelector('.side-head')).bottom]);
    document.querySelectorAll('.nav-group').forEach((g) => {
      const lineTop = r(g.querySelector('.nav-label')).top + 12;
      const prevEl = g.previousElementSibling ? g.previousElementSibling.querySelector('.nav-item:last-of-type') : document.querySelector('#quick-search');
      out.push([`${g.dataset.group}: icon above → line`, lineTop - r(prevEl).bottom]);
      out.push([`${g.dataset.group}: line → icon below`, r(g.querySelector('.nav-item')).top - (lineTop + 1)]);
    });
    return out;
  });
  for (const [name, gap] of gaps) assert.ok(Math.abs(gap - 12) <= 0.5, `${name} = ${gap}px (want 12)`);
  console.log('     gaps:', gaps.map(([n, g]) => `${n} ${Math.round(g)}`).join(' | '));
  await shot('sidebar-collapsed-dividers-light');
  const card = await page.locator('.side-card').boundingBox();
  await page.mouse.click(card.x + card.width / 2, card.y + card.height - 40);   // empty space
  await page.waitForTimeout(450);
  assert.equal(await page.getAttribute('html', 'data-sidebar'), null);
  assert.ok((await page.locator('.side-card').boundingBox()).width > 240);
  // Empty space in the OPEN sidebar does nothing (no accidental close)
  const open = await page.locator('.side-card').boundingBox();
  await page.mouse.click(open.x + open.width / 2, open.y + open.height - 40);
  await page.locator('.nav-label', { hasText: 'Voice' }).click();
  assert.equal(await page.getAttribute('html', 'data-sidebar'), null, 'empty space keeps open sidebar open');
  await page.click('#sidebar-toggle');
  assert.equal(await page.getAttribute('html', 'data-sidebar'), 'collapsed');
  // Logo toggles both ways
  await page.click('#side-logo');
  assert.equal(await page.getAttribute('html', 'data-sidebar'), null, 'logo opens');
  await page.click('#side-logo');
  assert.equal(await page.getAttribute('html', 'data-sidebar'), 'collapsed', 'logo closes');
  // Ctrl+B toggles both ways
  await page.keyboard.press('Control+b');
  assert.equal(await page.getAttribute('html', 'data-sidebar'), null, 'Ctrl+B opens');
  await page.keyboard.press('Control+b');
  assert.equal(await page.getAttribute('html', 'data-sidebar'), 'collapsed', 'Ctrl+B closes');
  await page.click('#side-logo');
  assert.equal(await page.getAttribute('html', 'data-sidebar'), null);
  // Clicking a nav item in the open sidebar navigates and does NOT collapse
  await page.click('.nav-item[data-page="recording"]');
  assert.equal(await page.getAttribute('html', 'data-sidebar'), null, 'nav click keeps sidebar open');
  pass('Sidebar: icons fixed in both states; even 12px rhythm; only page-list whitespace expands; logo + Ctrl+B toggle');

  // Quick search (Ctrl+K) jumps to a page
  await page.keyboard.press('Control+k');
  await page.fill('#search-input', 'clean');
  await shot('quick-search-light');
  await page.keyboard.press('Enter');
  assert.equal(await page.locator('#crumb').innerText(), 'Voice · Text cleanup');
  pass('Quick search filters and navigates');

  // Dictation card: click → recording → finish → processing → new history item
  await page.goto(url('page=home&theme=light'));
  const before = await page.locator('#recent-list .item').count();
  await page.click('#rec-btn');
  assert.equal(await page.getAttribute('#dictate', 'data-state'), 'recording');
  await page.waitForTimeout(1300);
  await shot('home-recording-light');
  await page.click('#rec-btn');
  assert.equal(await page.getAttribute('#dictate', 'data-state'), 'processing');
  assert.ok(await page.isDisabled('#rec-btn'));
  await shot('home-processing-light');
  await page.waitForFunction(() => document.querySelector('#dictate').dataset.state === 'idle', null, { timeout: 4000 });
  assert.match(await page.locator('#recent-list .item').first().innerText(), /Just now/);
  assert.ok(before > 0);
  pass('Card: idle → recording → processing → idle, item added');

  // Waveform (Frequency Lanes on Quiet Pillars): still at rest, reacts while listening, settles back
  await page.goto(url('page=home&theme=light'));
  const wv = () => page.evaluate(() => window.__wave.state());
  assert.equal(await page.evaluate(() => FrequencyLanes.SENSITIVITY), 3, 'mic sensitivity doubled (1.5× → 3×)');
  let st = await wv();
  assert.equal(st.heights.length, 29);
  assert.ok(st.heights.every((h) => h === 2), 'rest = Quiet Pillars (all 2px)');
  assert.equal(await page.evaluate(() => [document.querySelector('#wave').width, document.querySelector('#wave').height].join('x')), '680x144');
  await page.click('#rec-btn');
  await page.waitForFunction(() => window.__wave.state().mode !== 'requesting', null, { timeout: 5000 });
  st = await wv();
  assert.equal(st.mode, 'sample', 'no mic permission in this context → labelled synthetic input');
  assert.match(await page.locator('#dictate-eyebrow').innerText(), /simulated input/i);
  await page.waitForTimeout(1500);
  st = await wv();
  const hi = Math.max(...st.heights), lo = Math.min(...st.heights);
  assert.ok(hi > 10, `pillars rise while listening (max ${hi.toFixed(1)})`);
  assert.ok(hi - lo > 5, 'different pillars move independently');
  await shot('waveform-listening-light');
  await page.click('#rec-btn');                                            // finish → processing
  await page.waitForFunction(() => window.__wave.state().heights.every((h) => h === 2), null, { timeout: 2500 });
  assert.equal((await wv()).mode, 'idle');
  await page.waitForFunction(() => document.querySelector('#dictate').dataset.state === 'idle', null, { timeout: 4000 });
  pass('Waveform: still at rest; reacts to (synthetic) input; settles to exact rest after finishing');

  // Keyboard shortcut toggles; Esc discards
  await page.keyboard.press('Control+Shift+Space');
  assert.equal(await page.getAttribute('#dictate', 'data-state'), 'recording');
  await page.keyboard.press('Escape');
  assert.equal(await page.getAttribute('#dictate', 'data-state'), 'idle');
  pass('Ctrl+Shift+Space starts, Esc discards');

  // Recording page: mic test ends in "Sounds clear"; AirPods warns; no-mic → card warning
  await page.goto(url('page=recording&theme=light'));
  await page.click('#mic-test');
  await page.waitForTimeout(1200); await shot('recording-testing-light');
  await page.waitForFunction(() => /Sounds clear/.test(document.querySelector('#level-state').textContent), null, { timeout: 5000 });
  await page.selectOption('#mic-select', 'AirPods Pro'); await page.click('#mic-test');
  await page.waitForFunction(() => /quiet/.test(document.querySelector('#level-state').textContent), null, { timeout: 5000 });
  await shot('recording-quiet-light');
  pass('Mic test: live → sounds clear; low input → yellow warning');
  await page.selectOption('#shortcut-select', 'alt+Space');
  assert.match(await page.locator('#shortcut-desc').innerText(), /window menu/);
  await page.selectOption('#shortcut-select', 'F9');
  await page.click('#mode-seg [data-mode="hold"]');
  await page.selectOption('#mic-select', 'none');
  await page.click('.nav-item[data-page="home"]');
  assert.match(await page.locator('#dictate-hint').innerText(), /hold\s+F9/);
  await page.click('#rec-btn');
  assert.equal(await page.getAttribute('#dictate', 'data-state'), 'warning');
  await shot('home-warning-light');
  pass('Shortcut conflict warning, hold mode + F9 hint, no-mic card warning');

  // Models: failing test → red + nav dot; retry → green; cloud options gated by local switch
  await page.goto(url('page=models&theme=light'));
  const cleanup = page.locator('[data-model="cleanup"]');
  await cleanup.locator('select').selectOption({ index: 1 });
  await page.waitForTimeout(1000);
  await cleanup.locator('[data-test]').click();
  await page.waitForFunction(() => /Not reachable/.test(document.querySelector('[data-model="cleanup"] [data-status]').textContent), null, { timeout: 3000 });
  assert.equal(await page.isHidden('.nav-item[data-page="models"] .status-dot'), false);
  await shot('models-error-light');
  await cleanup.locator('[data-test]').click();
  await page.waitForFunction(() => /Ready ·/.test(document.querySelector('[data-model="cleanup"] [data-status]').textContent), null, { timeout: 3000 });
  assert.equal(await page.isHidden('.nav-item[data-page="models"] .status-dot'), true);
  assert.ok(await cleanup.locator('option[data-remote]').evaluate((o) => o.disabled));
  await page.click('#local-switch');
  assert.ok(!(await cleanup.locator('option[data-remote]').evaluate((o) => o.disabled)));
  pass('Model test error → retry → ready; local switch gates cloud options');

  // Cleanup: save disabled until edit; preview swaps; switch dims body
  await page.goto(url('page=cleanup&theme=light'));
  assert.ok(await page.isDisabled('#save-instructions'));
  await page.fill('#instructions', 'Keep it short.');
  assert.ok(!(await page.isDisabled('#save-instructions')));
  await page.click('#save-instructions');
  await page.waitForFunction(() => /Saved/.test(document.querySelector('#save-instructions').textContent));
  const firstPolished = await page.locator('#diff-polished').innerText();
  await page.click('#preview-example'); await page.waitForTimeout(400);
  assert.notEqual(await page.locator('#diff-polished').innerText(), firstPolished);
  await page.click('#cleanup-switch');
  assert.ok(await page.locator('#cleanup-body').evaluate((e) => e.classList.contains('is-off')));
  pass('Cleanup: save gating, preview example, polish switch');

  // Real audio path: Chromium's fake microphone (a test tone), permission granted
  {
    const micBrowser = await chromium.launch({ headless: true, args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'],
      env: { ...process.env, LD_LIBRARY_PATH: path.join(tools, 'libs/usr/lib/x86_64-linux-gnu') } });
    const ctx = await micBrowser.newContext({ viewport: { width: 1360, height: 900 } });
    await ctx.grantPermissions(['microphone']);
    const mp = await ctx.newPage();
    mp.on('pageerror', (e) => errors.push(e.message));
    await mp.goto(url('page=home&theme=dark'));
    await mp.click('#rec-btn');
    await mp.waitForFunction(() => window.__wave.state().mode === 'mic', null, { timeout: 5000 });
    let peak = 0;
    for (let i = 0; i < 20; i++) { await mp.waitForTimeout(100); peak = Math.max(peak, ...(await mp.evaluate(() => window.__wave.state().heights))); }
    assert.ok(peak > 4, `live mic moves the pillars (peak ${peak.toFixed(1)})`);
    await mp.screenshot({ path: path.join(shotsDir, 'waveform-mic-dark.png') });
    await mp.click('#rec-btn');
    await mp.waitForFunction(() => window.__wave.state().mode === 'idle' && window.__wave.state().heights.every((h) => h === 2), null, { timeout: 3000 });
    await micBrowser.close();
    pass('Waveform: real Web Audio path with a (fake) microphone; mic released and pillars at rest after finish');
  }

  assert.deepEqual(errors, [], 'no console/page errors');
  pass('No console or page errors');
} finally {
  await browser.close();
}
