/* Wispr Clone — UI demo behaviour.
   All data here is mock data; nothing is recorded, sent or stored. */
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const icon = (id, cls = 'i') => `<svg class="${cls}"><use href="#i-${id}"/></svg>`;
  const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const checkDraw = '<svg class="i check-draw" viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg>';
  const spinner = (px = 12) => `<span class="spinner" style="width:${px}px;height:${px}px;border-width:1.5px"></span>`;
  const replay = (el, cls) => { el.classList.remove(cls); void el.offsetWidth; el.classList.add(cls); };

  /* ---------------- Mock data ---------------- */
  const history = [
    { id: 1, app: 'Slack', tile: 'S', when: '2 min ago', words: 38, status: 'cleaned',
      text: "Hey team, quick update: the onboarding flow is ready for review. I've left comments on the two screens I'm unsure about.",
      original: "hey team um quick update the onboarding flow is uh ready for review I've left like comments on the two screens I'm unsure about" },
    { id: 2, app: 'VS Code', tile: '{}', when: '18 min ago', words: 21, status: 'failed',
      text: 'so the useEffect should um only run when the the user id changes not on every render',
      original: 'so the useEffect should um only run when the the user id changes not on every render' },
    { id: 3, app: 'Gmail', tile: 'M', when: '1 hr ago', words: 64, status: 'cleaned',
      text: 'Hi Dana, thanks for sending the contract over. I reviewed sections 3 and 4 and they look good. Could we move the start date to October 6th?',
      original: 'hi dana thanks for sending the contract over I reviewed uh sections three and four and they look good could we move the start date to october sixth' },
    { id: 4, app: 'Notion', tile: 'N', when: 'Yesterday', words: 112, status: 'cleaned',
      text: 'Retro notes: shipping the local-only mode went smoothly. Next sprint we focus on dictionary import and a faster cold start.',
      original: 'retro notes shipping the local only mode went smoothly next sprint we focus on dictionary import and a faster cold start' },
    { id: 5, app: 'Linear', tile: 'L', when: 'Yesterday', words: 17, status: 'raw',
      text: 'Bug: floating pill overlaps the macOS dock when it is set to auto-hide.',
      original: 'bug floating pill overlaps the mac OS dock when it is set to auto hide' },
  ];
  const samples = [
    { app: 'Slack', tile: 'S', text: "Sounds good — let's sync after lunch and lock the release notes then.", original: "sounds good uh let's sync after lunch and like lock the release notes then" },
    { app: 'Figma', tile: 'F', text: 'Can we try the record button 8px larger and soften the glow in dark mode?', original: 'can we try the record button eight pixels larger and um soften the glow in dark mode' },
    { app: 'Gmail', tile: 'M', text: "Thanks Priya, I'll have the Kubernetes migration plan to you by Thursday.", original: "thanks priya I'll have the cooper netties migration plan to you by thursday" },
  ];
  const dictionary = [
    { term: 'Kubernetes', alias: ['cooper netties', 'kuber nets'], added: 'Sep 18' },
    { term: 'Wispr', alias: ['whisper'], added: 'Sep 12' },
    { term: 'Priya Raman', alias: ['pria ramen'], added: 'Sep 10' },
    { term: 'useEffect', alias: ['use effect'], added: 'Sep 8' },
    { term: 'PostgreSQL', alias: ['postgres q l', 'post gress'], added: 'Aug 30' },
    { term: 'Tauri', alias: ['tory', 'tarry'], added: 'Aug 22' },
  ];
  const cleanupExamples = [
    { o: "“So, um, let's move the design review to Thursday. And, uh, bring the new mockups.”", p: "Let's move the design review to Thursday. Bring the new mockups." },
    { o: '“I think we should — I mean I think we could probably ship it, like, Friday?”', p: 'I think we could probably ship it Friday.' },
    { o: '“Can you, uh, send me the the numbers from last quarter when you get a sec.”', p: 'Can you send me the numbers from last quarter when you get a second?' },
  ];

  /* ---------------- Toasts ---------------- */
  const toastIcons = { success: 'check-circle', info: 'info', warning: 'alert', danger: 'error' };
  function toast(kind, title, body = '', action) {
    const el = document.createElement('div');
    el.className = `toast ${kind}`;
    el.setAttribute('role', kind === 'danger' ? 'alert' : 'status');
    el.innerHTML = `<span class="toast-icon">${kind === 'success' ? checkDraw : icon(toastIcons[kind])}</span>
      <div><strong>${title}</strong><span class="muted">${body}</span></div>
      ${action ? `<button class="btn btn-ghost btn-sm">${action.label}</button>` : ''}`;
    const dismiss = () => { el.classList.add('is-leaving'); setTimeout(() => el.remove(), 200); };
    if (action) el.querySelector('button').onclick = () => { action.run(); dismiss(); };
    $('#toasts').append(el);
    setTimeout(dismiss, 4000);
  }

  /* ---------------- Theme ---------------- */
  const mq = matchMedia('(prefers-color-scheme: dark)');
  let themePref = new URLSearchParams(location.search).get('theme') || localStorage.getItem('wc-theme') || 'light';
  function applyTheme() {
    const resolved = themePref === 'system' ? (mq.matches ? 'dark' : 'light') : themePref;
    document.documentElement.dataset.theme = resolved;
    $$('#theme-seg button').forEach((b) => b.setAttribute('aria-checked', b.dataset.themeSet === themePref));
    localStorage.setItem('wc-theme', themePref);
  }
  $$('#theme-seg button').forEach((b) => (b.onclick = () => { themePref = b.dataset.themeSet; applyTheme(); }));
  mq.addEventListener('change', applyTheme);

  /* ---------------- Navigation (single sidebar) ---------------- */
  function go(id) {
    $$('.page').forEach((p) => p.classList.toggle('is-active', p.id === `page-${id}`));
    $$('.nav-item[data-page]').forEach((n) => (n.dataset.page === id ? n.setAttribute('aria-current', 'page') : n.removeAttribute('aria-current')));
    $('#crumb').textContent = $(`#page-${id}`).dataset.title;
    $('#main').scrollTop = 0;
  }
  const openSettings = go;
  $$('.nav-item[data-page]').forEach((n) => (n.onclick = () => go(n.dataset.page)));
  $$('[data-goto]').forEach((b) => (b.onclick = () => go(b.dataset.goto)));

  /* ---------------- Sidebar: collapse / expand ----------------
     Toggle: logo or Ctrl+B. Collapse: header button. Expand: empty space in
     the collapsed strip. Icons stay usable while collapsed. */
  const sidebarOpen = () => document.documentElement.dataset.sidebar !== 'collapsed';
  function setSidebar(open) {
    const root = document.documentElement;
    open ? delete root.dataset.sidebar : (root.dataset.sidebar = 'collapsed');
    const btn = $('#sidebar-toggle');
    btn.setAttribute('aria-expanded', open);
    $('#side-logo').setAttribute('aria-label', open ? 'Collapse sidebar' : 'Expand sidebar');
    $('#side-logo').setAttribute('aria-expanded', open);
    localStorage.setItem('wc-sidebar', open ? 'open' : 'collapsed');
    hideTip();
  }
  $('#sidebar-toggle').onclick = () => setSidebar(false);
  // Logo and Ctrl+B toggle both ways. Empty space only EXPANDS the collapsed strip,
  // so a missed click in the open sidebar never closes it by accident.
  $('#side-logo').onclick = () => setSidebar(!sidebarOpen());
  $('.side-card').addEventListener('click', (e) => {
    // Only empty space in the page list expands the strip. Header, search row,
    // and group dividers (.nav-label) are not triggers.
    if (!sidebarOpen() && e.target.closest('.side-scroll') && !e.target.closest('button, .nav-label')) setSidebar(true);
  });
  document.addEventListener('keydown', (e) => {
    if (e.ctrlKey && !e.shiftKey && !e.altKey && e.code === 'KeyB') { e.preventDefault(); setSidebar(!sidebarOpen()); }
  });

  // Tooltips on the collapsed strip (hover or keyboard focus)
  const tip = $('#tip');
  let tipTimer;
  function showTip(el) {
    if (sidebarOpen()) return;
    const r = el.getBoundingClientRect();
    tip.textContent = el.dataset.tip;
    tip.style.left = `${r.right + 12}px`;
    tip.style.top = `${r.top + r.height / 2}px`;
    clearTimeout(tipTimer);
    tipTimer = setTimeout(() => tip.classList.add('is-on'), 60);
  }
  function hideTip() { clearTimeout(tipTimer); tip.classList.remove('is-on'); }
  $$('#sidebar [data-tip]').forEach((el) => {
    el.addEventListener('mouseenter', () => showTip(el));
    el.addEventListener('mouseleave', hideTip);
    el.addEventListener('focus', () => showTip(el));
    el.addEventListener('blur', hideTip);
  });
  setSidebar(sidebarOpen());

  /* ---------------- Generic controls ---------------- */
  document.addEventListener('click', (e) => {
    const sw = e.target.closest('.switch');
    if (sw && !sw.disabled) {
      sw.setAttribute('aria-checked', sw.getAttribute('aria-checked') !== 'true');
      sw.dispatchEvent(new CustomEvent('toggle', { bubbles: true }));
    }
  });
  const isOn = (sw) => sw.getAttribute('aria-checked') === 'true';
  function segmented(root, onChange) {
    $$('button', root).forEach((b) => b.addEventListener('click', () => {
      $$('button', root).forEach((x) => x.setAttribute('aria-checked', x === b));
      onChange && onChange(b);
    }));
  }

  const hr = new Date().getHours();
  $('#greet').textContent = hr < 12 ? 'Good morning' : hr < 18 ? 'Good afternoon' : 'Good evening';

  /* ---------------- Transcript lists ---------------- */
  function itemHtml(it, showOriginal) {
    const statusBadge = {
      cleaned: `<span class="badge accent">${icon('sparkles')}Cleaned</span>`,
      raw: `<span class="badge">Raw</span>`,
      failed: `<span class="badge warning">${icon('alert')}Cleanup failed</span>`,
    }[it.status];
    const actions = it.status === 'failed'
      ? `<button class="btn btn-secondary btn-sm" data-retry="${it.id}">${icon('refresh')}Retry cleanup</button>`
      : `<button class="btn btn-ghost btn-icon btn-sm" title="Show original" data-orig="${it.id}" aria-label="Show original">${icon('eye')}</button>
         <button class="btn btn-ghost btn-icon btn-sm" title="Copy" data-copy="${it.id}" aria-label="Copy">${icon('copy')}</button>
         <button class="btn btn-ghost btn-icon btn-sm danger" title="Delete" data-del="${it.id}" aria-label="Delete">${icon('trash')}</button>`;
    return `<div class="item ${it.status === 'failed' ? 'is-failed' : ''} ${it.isNew ? 'is-new' : ''}" data-id="${it.id}">
      <span class="app-tile">${esc(it.tile)}</span>
      <div class="item-body">
        <div class="item-meta"><strong>${esc(it.app)}</strong><span>·</span><span>${it.when}</span><span>·</span><span>${it.words} words</span>${statusBadge}</div>
        <div class="item-text ${showOriginal ? 'original' : ''}">${esc(showOriginal ? it.original : it.text)}</div>
      </div>
      <div class="item-actions">${actions}</div>
    </div>`;
  }
  let filter = 'all';
  const showingOriginal = new Set();
  function renderLists() {
    $('#recent-list').innerHTML = history.slice(0, 3).map((it) => itemHtml(it, showingOriginal.has(it.id))).join('')
      || `<div class="empty"><h3>No dictations yet</h3><p class="muted">Press Start dictation to create your first one.</p></div>`;
    const q = $('#history-search').value.toLowerCase();
    const rows = history.filter((it) =>
      (filter === 'all' || (filter === 'failed' ? it.status === 'failed' : it.status === 'cleaned')) &&
      (!q || it.text.toLowerCase().includes(q) || it.app.toLowerCase().includes(q)));
    $('#history-list').innerHTML = rows.length
      ? rows.map((it) => itemHtml(it, showingOriginal.has(it.id))).join('')
      : `<div class="empty"><div class="row-icon">${icon('history', 'i i-lg')}</div><h3>Nothing here</h3><p class="muted">${history.length ? 'No transcripts match this filter.' : 'Your dictations will appear here.'}</p></div>`;
    history.forEach((it) => (it.isNew = false));
    $('#hist-count').textContent = history.length;
    $('.nav-item[data-page="history"] .status-dot').hidden = !history.some((i) => i.status === 'failed');
    $('#hist-nav-count').textContent = history.length;
  }
  $('#history-search').oninput = renderLists;
  segmented($('#history-filter'), (b) => { filter = b.dataset.filter; renderLists(); });

  document.addEventListener('click', (e) => {
    const t = e.target.closest('[data-copy],[data-del],[data-retry],[data-orig]');
    if (!t) return;
    const id = +(t.dataset.copy || t.dataset.del || t.dataset.retry || t.dataset.orig);
    const it = history.find((x) => x.id === id);
    if (t.dataset.copy) {
      navigator.clipboard?.writeText(it.text).catch(() => {});
      t.innerHTML = checkDraw; t.style.color = 'var(--green-text)';
      setTimeout(() => { t.innerHTML = icon('copy'); t.style.color = ''; }, 1400);
    } else if (t.dataset.orig) {
      showingOriginal.has(id) ? showingOriginal.delete(id) : showingOriginal.add(id);
      renderLists();
    } else if (t.dataset.del) {
      const idx = history.indexOf(it);
      history.splice(idx, 1);
      renderLists();
      toast('info', 'Transcript deleted', '', { label: 'Undo', run: () => { history.splice(idx, 0, it); renderLists(); } });
    } else if (t.dataset.retry) {
      t.classList.add('is-loading');
      setTimeout(() => {
        Object.assign(it, { status: 'cleaned', text: 'So the useEffect should only run when the user ID changes, not on every render.' });
        renderLists();
        toast('success', 'Cleanup complete', 'Transcript updated in History.');
      }, 1300);
    }
  });

  /* ---------------- Level meters (pill + styleguide) ---------------- */
  function buildMeter(el, n) { el.innerHTML = '<i></i>'.repeat(n); return $$('i', el); }
  function driveMeter(bars, level = 1) {
    bars.forEach((b, i) => {
      const center = 1 - Math.abs(i - bars.length / 2) / (bars.length / 2);
      const v = Math.min(1, (0.15 + Math.random() * 0.85) * (0.45 + center * 0.55) * level);
      b.style.height = `${Math.max(15, v * 100)}%`;
      b.classList.toggle('hot', v > 0.86);
    });
  }
  const pillBars = buildMeter($('#pill-meter'), 14);
  const sgBars = buildMeter($('#sg-meter'), 12);
  setInterval(() => driveMeter(sgBars), 110);

  /* ---------------- Dictation card waveform (Frequency Lanes) ---------------- */
  const wave = FrequencyLanes.create($('#wave'), {
    color: () => getComputedStyle($('#dictate')).getPropertyValue('--wave-color').trim(),
  });
  // Recolour on theme change (the canvas doesn't inherit CSS colour by itself)
  new MutationObserver(() => wave.redraw()).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  window.__wave = wave;   // review/test hook only

  /* ---------------- Shortcut + mode (shared by card and settings) ---------------- */
  let mode = 'toggle';
  let shortcut = 'ctrl+shift+Space';
  const shortcutLabel = () => $('#shortcut-select').selectedOptions[0].textContent;
  function matchesShortcut(e) {
    const parts = shortcut.split('+'); const code = parts.pop();
    return e.code === code && e.ctrlKey === parts.includes('ctrl') && e.shiftKey === parts.includes('shift') && e.altKey === parts.includes('alt');
  }
  const mainCode = () => shortcut.split('+').pop();

  /* ---------------- Recording state machine ----------------
     idle → recording → processing → idle (+ new history item)
     recording → (Esc / Discard) → idle
     idle → (no microphone) → warning                               */
  const card = $('#dictate');
  let state = 'idle', timerId, meterId, startedAt, sampleIdx = 0, holding = false;
  const statusEl = $('#title-status');
  function setTitleStatus(kind, label, spin = false) {
    statusEl.className = `badge ${kind === 'success' ? '' : kind}`;
    statusEl.innerHTML = spin ? `${spinner(10)}${label}` : `<span class="status-dot ${kind} ${kind === 'danger' ? 'live' : ''}"></span>${label}`;
  }
  function hintHtml() {
    const k = `<kbd class="shortcut-label">${shortcutLabel()}</kbd>`;
    if (state === 'recording') return mode === 'hold' ? `release ${k} to finish` : `or press ${k} again`;
    return `or ${mode === 'hold' ? 'hold' : 'press'} ${k}`;
  }
  function render() {
    card.dataset.state = state;
    const btn = $('#rec-btn'), pill = $('#pill');
    const set = (status, eyebrow, caption, btnHtml) => {
      $('#dictate-status').innerHTML = status; $('#dictate-eyebrow').textContent = eyebrow;
      $('#dictate-caption').textContent = caption; btn.innerHTML = btnHtml;
    };
    btn.disabled = state === 'processing';
    $('#dictate-hint').innerHTML = hintHtml();
    $('#dictate-hint').style.visibility = state === 'processing' || state === 'warning' ? 'hidden' : '';
    if (state === 'recording') {
      set(`<span class="status-dot danger live"></span>Listening <span class="timer" id="card-timer">0:00</span>`, mode === 'hold' ? 'Hold to talk' : 'Press to toggle',
        'Go ahead — say it the way you would to a friend.', `${icon('stop')}<span>Finish dictation</span>`);
      btn.className = 'btn btn-record';
      pill.classList.add('is-open');
      setTitleStatus('danger', 'Listening');
    } else if (state === 'processing') {
      set(`${spinner(14)}Polishing your words`, 'Working', 'Removing the little hesitations…', `${spinner(16)}<span>Working…</span>`);
      btn.className = 'btn btn-primary btn-record';
      setTitleStatus('info', 'Transcribing', true);
    } else if (state === 'warning') {
      set(`<span style="color:var(--yellow-text);display:inline-flex;gap:8px;align-items:center">${icon('alert')}No microphone detected</span>`, 'Needs attention',
        'Choose an input in Recording settings, then try again.', `${icon('settings')}<span>Choose microphone</span>`);
      btn.className = 'btn btn-secondary btn-record';
      setTitleStatus('warning', 'No input');
    } else {
      set(`${icon('wave')}Ready when you are`, 'Try it out', 'From a passing thought to the perfect words.', `${icon('mic')}<span>Start dictation</span>`);
      btn.className = 'btn btn-primary btn-record';
      pill.classList.remove('is-open');
      setTitleStatus('success', 'Ready');
    }
    $('#pill-dot').className = state === 'processing' ? 'spinner' : 'status-dot danger live';
    $('#pill-dot').style.cssText = state === 'processing' ? 'width:12px;height:12px;border-width:2px' : '';
    $('#pill-label').textContent = state === 'processing' ? 'Transcribing' : 'Listening';
    $('#pill-meter').style.display = state === 'processing' ? 'none' : '';
  }
  function setState(next) {
    clearInterval(timerId); clearInterval(meterId);
    state = next;
    render();
    if (next === 'recording') {
      startedAt = Date.now();
      meterId = setInterval(() => {
        const h = wave.heights();
        pillBars.forEach((b, i) => { const v = (h[i * 2] - FrequencyLanes.REST) / 57; b.style.height = `${Math.round(18 + 82 * Math.min(1, v * 1.6))}%`; });
      }, 60);
      wave.start().then((source) => {
        if (source === 'sample' && state === 'recording') $('#dictate-eyebrow').textContent = `${mode === 'hold' ? 'Hold to talk' : 'Press to toggle'} · simulated input`;
      });
      timerId = setInterval(() => {
        const s = Math.floor((Date.now() - startedAt) / 1000);
        const t = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
        $('#pill-timer').textContent = t; const ct = $('#card-timer'); if (ct) ct.textContent = t;
      }, 250);
    } else if (next === 'processing') {
      wave.stop();                                   // pillars settle to rest; spinner shows the work
      setTimeout(finish, 1500);
    } else {
      wave.stop();
      pillBars.forEach((b) => (b.style.height = '20%'));
      $('#pill-timer').textContent = '0:00';
    }
  }
  function finish() {
    const s = samples[sampleIdx++ % samples.length];
    const polish = isOn($('#cleanup-switch'));
    const cleanupBroken = $('[data-model="cleanup"]').classList.contains('is-error');
    const status = !polish ? 'raw' : cleanupBroken ? 'failed' : 'cleaned';
    const text = status === 'cleaned' ? s.text : s.original;
    const words = text.split(/\s+/).length;
    history.unshift({ id: Date.now(), when: 'Just now', words, status, isNew: true, ...s, text });
    const w = $('#stat-words'); w.textContent = (parseInt(w.textContent.replace(/,/g, ''), 10) + words).toLocaleString();
    renderLists();
    setState('idle');
    if (status === 'failed') toast('warning', `Inserted into ${s.app} without cleanup`, 'The cleanup model didn’t respond.', { label: 'Models', run: () => openSettings('models') });
    else toast('success', `Inserted into ${s.app}`, `${words} words · ${status === 'raw' ? 'raw transcript' : 'polished'}`);
  }
  const noMic = () => $('#mic-select').value === 'none';
  function start() {
    if (noMic()) { setState('warning'); wave.redraw(); replay(card, 'shake'); return; }
    setState('recording');
  }
  function primaryAction() {
    if (state === 'idle') start();
    else if (state === 'recording') setState('processing');
    else if (state === 'warning') { setState('idle'); wave.redraw(); openSettings('recording'); $('#mic-select').focus(); }
  }
  function cancel() {
    if (state !== 'recording') return;
    setState('idle');
    toast('info', 'Dictation discarded', 'Nothing was inserted.');
  }
  $('#rec-btn').onclick = primaryAction;
  $('#dictate-cancel').onclick = cancel;
  $('#pill-cancel').onclick = cancel;

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { if ($('.backdrop.is-open')) return closeModals(); return cancel(); }
    if (!matchesShortcut(e) || e.repeat) return;
    e.preventDefault();
    if (mode === 'hold') { if (state === 'idle') { holding = true; start(); } }
    else primaryAction();
  });
  document.addEventListener('keyup', (e) => {
    if (holding && e.code === mainCode()) { holding = false; if (state === 'recording') setState('processing'); }
  });

  /* ---------------- Settings › Recording ---------------- */
  segmented($('#mode-seg'), (b) => {
    mode = b.dataset.mode;
    $('#mode-desc').textContent = mode === 'hold'
      ? 'Hold the shortcut while speaking; release to finish.'
      : 'Use the shortcut below while this demo tab has focus.';
    render();
  });

  $('#shortcut-select').onchange = (e) => {
    shortcut = e.target.value;
    const desc = $('#shortcut-desc');
    if (shortcut === 'alt+Space') {
      desc.innerHTML = `<span style="color:var(--yellow-text);display:inline-flex;gap:6px;align-items:center">${icon('alert')}Alt + Space opens the window menu on Windows. Pick another shortcut.</span>`;
      replay($('#shortcut-row'), 'shake');
    } else {
      desc.textContent = 'Start and finish a dictation from this browser tab.';
      toast('success', 'Shortcut updated', `Dictation now uses ${shortcutLabel()}.`);
    }
    render();
  };

  $('#mic-select').onchange = () => { if (state === 'warning' && !noMic()) setState('idle'); resetLevel(); };

  // Simulated input level: 36 segments, green → yellow at the top end
  const SEG = 36;
  const segs = buildMeter($('#level-segments'), SEG);
  let levelTimer = null, levelStop = null;
  function setLevelState(kind, html) { const el = $('#level-state'); el.className = `level-state ${kind}`; el.innerHTML = html; }
  function paint(n) { segs.forEach((s, i) => (s.className = i < n ? (i >= SEG * 0.8 ? 'warm' : 'on') : '')); }
  function resetLevel() {
    clearInterval(levelTimer); clearTimeout(levelStop); levelTimer = null;
    paint(0);
    $('#mic-test').innerHTML = `${icon('mic')}Test microphone`;
    setLevelState('idle', 'Waiting for a test');
  }
  $('#mic-test').onclick = () => {
    if (levelTimer) return resetLevel();
    const input = $('#mic-select').value;
    const gain = input === 'none' ? 0 : input === 'AirPods Pro' ? 0.28 : 0.72;
    $('#mic-test').innerHTML = `${icon('stop')}Stop test`;
    setLevelState('live', `${spinner(10)}Listening…`);
    let smooth = 0;
    levelTimer = setInterval(() => {
      const target = gain * SEG * (0.55 + Math.random() * 0.6);
      smooth += (target - smooth) * 0.45;
      paint(Math.round(smooth));
    }, 80);
    levelStop = setTimeout(() => {
      clearInterval(levelTimer); levelTimer = null;
      $('#mic-test').innerHTML = `${icon('refresh')}Test again`;
      if (gain === 0) { paint(0); setLevelState('quiet', `${icon('alert')}We can't hear anything`); replay($('#level-segments'), 'shake'); }
      else if (gain < 0.4) { paint(Math.round(SEG * 0.25)); setLevelState('quiet', `${icon('alert')}A little quiet — move closer`); replay($('#level-segments'), 'shake'); }
      else { paint(Math.round(SEG * 0.6)); setLevelState('good', `${checkDraw}Sounds clear`); }
    }, 3200);
  };

  /* ---------------- Settings › Models ---------------- */
  function setModelStatus(cardEl, kind, html) {
    cardEl.querySelector('[data-status]').outerHTML = `<span class="badge ${kind}" data-status>${html}</span>`;
  }
  function syncModelsDot() {
    const dot = $('.nav-item[data-page="models"] .status-dot');
    dot.className = 'status-dot danger';
    dot.hidden = !$$('.model-card.is-error').length;
  }
  function syncRemoteOptions() {
    const local = isOn($('#local-switch'));
    $$('.model-card').forEach((c) => {
      const sel = $('[data-select]', c);
      $$('option[data-remote]', sel).forEach((o) => (o.disabled = local));
      if (local && sel.selectedOptions[0].hasAttribute('data-remote')) { sel.selectedIndex = 0; sel.dispatchEvent(new Event('change')); }
    });
  }
  $$('.model-card').forEach((c) => {
    const sel = $('[data-select]', c), testBtn = $('[data-test]', c);
    let failedOnce = false;
    sel.onchange = () => {
      const opt = sel.selectedOptions[0];
      c.classList.remove('is-error'); syncModelsDot();
      $('.model-meta [data-where]', c).textContent = opt.dataset.where;
      setModelStatus(c, 'info', `${spinner(10)}Loading`);
      setTimeout(() => {
        if (opt.hasAttribute('data-remote')) setModelStatus(c, 'warning', `${icon('alert')}Leaves this device`);
        else setModelStatus(c, 'success', '<span class="status-dot success"></span>Ready · demo');
      }, 900);
    };
    const runTest = () => {
      const opt = sel.selectedOptions[0];
      testBtn.classList.add('is-loading');
      setModelStatus(c, 'info', `${spinner(10)}Testing`);
      setTimeout(() => {
        testBtn.classList.remove('is-loading');
        if (opt.hasAttribute('data-fails') && !failedOnce) {
          failedOnce = true;
          c.classList.add('is-error'); syncModelsDot(); replay(c, 'shake');
          setModelStatus(c, 'danger', '<span class="status-dot danger"></span>Not reachable');
          toast('danger', 'Couldn’t reach Ollama', 'Start Ollama, then test again.', { label: 'Retry', run: runTest });
        } else {
          c.classList.remove('is-error'); syncModelsDot();
          const ms = 120 + Math.round(Math.random() * 140);
          setModelStatus(c, 'success', `<span class="status-dot success"></span>Ready · ${ms} ms`);
          toast('success', `${opt.textContent} responded`, `Round trip ${ms} ms · simulated`);
        }
      }, 1200);
    };
    testBtn.onclick = runTest;
  });
  $('#local-switch').addEventListener('toggle', () => {
    const local = isOn($('#local-switch'));
    syncRemoteOptions();
    toast('info', local ? 'Local only' : 'Cloud models allowed', local ? 'Cloud options are disabled.' : 'Cloud options can now be selected.');
  });
  syncRemoteOptions();

  /* ---------------- Settings › Text cleanup ---------------- */
  $('#cleanup-switch').addEventListener('toggle', () => {
    const on = isOn($('#cleanup-switch'));
    $('#cleanup-body').classList.toggle('is-off', !on);
    $('#instructions').disabled = !on;
  });
  const ta = $('#instructions');
  let savedText = ta.value;
  ta.oninput = () => {
    const dirty = ta.value !== savedText;
    $('#save-instructions').disabled = !dirty;
    $('#save-instructions').innerHTML = `${icon('check')}Save instructions`;
    $('#save-note').textContent = dirty ? 'Unsaved changes' : 'Saved as a preference; not sent to a model.';
  };
  $('#save-instructions').onclick = (e) => {
    const b = e.currentTarget;
    b.classList.add('is-loading');
    setTimeout(() => {
      b.classList.remove('is-loading'); b.disabled = true;
      savedText = ta.value;
      b.innerHTML = `${checkDraw}Saved`;
      $('#save-note').textContent = 'Saved just now.';
    }, 700);
  };
  let exIdx = 0;
  $('#preview-example').onclick = () => {
    const d = $('#difference');
    exIdx = (exIdx + 1) % cleanupExamples.length;
    d.classList.add('is-swapping');
    setTimeout(() => {
      $('#diff-original').textContent = cleanupExamples[exIdx].o;
      $('#diff-polished').textContent = cleanupExamples[exIdx].p;
      d.classList.remove('is-swapping');
    }, 200);
  };

  /* ---------------- Quick search (Ctrl+K) ---------------- */
  const pages = $$('.nav-item[data-page]').map((n) => ({
    id: n.dataset.page, label: n.dataset.tip,
    group: n.closest('.nav-group').dataset.group,
    icon: n.querySelector('use').getAttribute('href').slice(3),
  }));
  let results = [], sel = 0;
  function renderSearch() {
    const q = $('#search-input').value.trim().toLowerCase();
    results = pages.filter((p) => !q || p.label.toLowerCase().includes(q) || p.group.toLowerCase().includes(q));
    sel = Math.min(sel, Math.max(0, results.length - 1));
    $('#search-list').innerHTML = results.length
      ? results.map((p, i) => `<button class="palette-item ${i === sel ? 'is-active' : ''}" role="option" aria-selected="${i === sel}" data-go="${p.id}">${icon(p.icon)}<span>${p.label}</span><span class="group">${p.group}</span></button>`).join('')
      : '<div class="palette-empty">No pages match.</div>';
  }
  function openSearch() { $('#search-input').value = ''; sel = 0; renderSearch(); openModal('search-modal'); }
  function pick(id) { closeModals(); go(id); }
  $('#quick-search').onclick = openSearch;
  $('#search-input').oninput = () => { sel = 0; renderSearch(); };
  $('#search-input').addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      sel = (sel + (e.key === 'ArrowDown' ? 1 : -1) + results.length) % Math.max(1, results.length);
      renderSearch();
    } else if (e.key === 'Enter' && results[sel]) { e.preventDefault(); pick(results[sel].id); }
  });
  $('#search-list').addEventListener('click', (e) => { const b = e.target.closest('[data-go]'); if (b) pick(b.dataset.go); });
  document.addEventListener('keydown', (e) => {
    if (e.ctrlKey && !e.shiftKey && !e.altKey && e.code === 'KeyK') { e.preventDefault(); openSearch(); }
  });

  /* ---------------- Dictionary ---------------- */
  function renderDict() {
    const q = $('#dict-search').value.toLowerCase();
    const rows = dictionary.filter((d) => !q || d.term.toLowerCase().includes(q) || d.alias.some((a) => a.includes(q)));
    $('#dict-body').innerHTML = rows.map((d) => `<tr data-term="${esc(d.term)}" ${d.isNew ? 'class="item is-new" style="display:table-row"' : ''}>
      <td class="term">${esc(d.term)}</td>
      <td><div class="chips">${d.alias.map((a) => `<span class="chip">${esc(a)}</span>`).join('') || '<span class="faint">—</span>'}</div></td>
      <td class="faint">${d.added}</td>
      <td class="actions"><div>
        <button class="btn btn-ghost btn-icon btn-sm" aria-label="Edit ${esc(d.term)}">${icon('pencil')}</button>
        <button class="btn btn-ghost btn-icon btn-sm danger" aria-label="Delete ${esc(d.term)}" data-del-term="${esc(d.term)}">${icon('trash')}</button>
      </div></td></tr>`).join('');
    dictionary.forEach((d) => (d.isNew = false));
    $('#dict-empty').hidden = rows.length > 0;
    $('.table thead').style.display = rows.length ? '' : 'none';
    $('#dict-count').textContent = dictionary.length;
  }
  $('#dict-search').oninput = renderDict;
  $('#dict-body').addEventListener('click', (e) => {
    const b = e.target.closest('[data-del-term]');
    if (!b) return;
    b.closest('tr').classList.add('is-removing');
    setTimeout(() => {
      const idx = dictionary.findIndex((d) => d.term === b.dataset.delTerm);
      const [removed] = dictionary.splice(idx, 1);
      renderDict();
      toast('info', `Removed “${removed.term}”`, '', { label: 'Undo', run: () => { dictionary.splice(idx, 0, removed); renderDict(); } });
    }, 240);
  });

  /* ---------------- Modals ---------------- */
  let lastFocus;
  function openModal(id) {
    lastFocus = document.activeElement;
    const m = $(`#${id}`);
    m.classList.add('is-open');
    setTimeout(() => ($('input', m) || $('.btn-ghost', m)).focus(), 60);
  }
  function closeModals() {
    $$('.backdrop.is-open').forEach((m) => m.classList.remove('is-open'));
    lastFocus?.focus?.();
  }
  $$('[data-close]').forEach((b) => (b.onclick = closeModals));
  $$('.backdrop').forEach((bd) => bd.addEventListener('mousedown', (e) => { if (e.target === bd) closeModals(); }));
  $$('[data-open]').forEach((b) => (b.onclick = () => openModal(b.dataset.open)));

  $('#delete-all').onclick = () => openModal('delete-modal');
  $('#confirm-delete').onclick = (e) => {
    const btn = e.currentTarget;
    btn.classList.add('is-loading');
    setTimeout(() => {
      btn.classList.remove('is-loading');
      const n = history.length;
      history.length = 0; renderLists(); closeModals();
      toast('success', 'History deleted', `${n} transcripts removed.`);
    }, 900);
  };

  $('#add-term').onclick = () => { $('#term-input').value = ''; $('#alias-input').value = ''; $('#save-term').disabled = true; openModal('term-modal'); };
  $('#term-input').oninput = () => ($('#save-term').disabled = !$('#term-input').value.trim());
  $('#save-term').onclick = () => {
    const term = $('#term-input').value.trim();
    const alias = $('#alias-input').value.split(',').map((s) => s.trim().toLowerCase()).filter(Boolean);
    dictionary.unshift({ term, alias, added: 'Today', isNew: true });
    $('#dict-search').value = '';
    renderDict(); closeModals();
    toast('success', `Added “${term}”`, 'Applies to your next dictation.');
  };
  $('#term-input').addEventListener('keydown', (e) => { if (e.key === 'Enter' && !$('#save-term').disabled) $('#save-term').click(); });

  /* ---------------- Styleguide ---------------- */
  $('#ramp').innerHTML = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950]
    .map((s) => `<div style="background:var(--p-${s});color:${s >= 500 ? '#fff' : 'var(--p-900)'}">${s}</div>`).join('');
  $$('[data-replay]').forEach((b) => (b.onclick = () => {
    if (b.dataset.replay === 'shake') replay(b.previousElementSibling, 'shake');
    else { const c = $('#sg-check'); c.innerHTML = c.innerHTML; }
  }));
  $$('[data-toast]').forEach((b) => (b.onclick = () => b.dataset.toast === 'success'
    ? toast('success', 'Settings saved', 'Changes apply immediately.')
    : toast('danger', 'Microphone unavailable', 'Another app is using it.', { label: 'Retry', run: () => {} })));

  /* ---------------- Init ---------------- */
  applyTheme();
  render();
  renderLists();
  renderDict();
  const params = new URLSearchParams(location.search);
  // Deep links: ?page=<id>. The design-system sheet is review-only: ?page=styleguide
  go(params.get('page') || params.get('view') || 'home');
  // Review-only hook: ?state=recording|warning previews a dictation-card state
  const st = params.get('state');
  if (st === 'warning') { $('#mic-select').value = 'none'; start(); }
  else if (st === 'recording') setState('recording');
})();
