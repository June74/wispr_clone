'use strict';

// Review prototype: every recording, connection and model result is simulated.
// No microphone access, network requests, or app-to-app text insertion occurs.
const paths = {
  wave:'M3 10v4m4-8v12m5-15v18m5-16v14m4-10v6',
  mic:'M12 15a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v7a3 3 0 0 0 3 3ZM5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8',
  home:'m3 11 9-8 9 8M5 10v10h5v-6h4v6h5V10',
  history:'M3 11a9 9 0 1 1 2 7M3 4v7h7m2-5v6l4 2',
  book:'M4 3h13a2 2 0 0 1 2 2v16H6a3 3 0 0 1 0-6h13M4 3v15M8 7h7m-7 4h5',
  settings:'M4 7h16M4 17h16M9 4v6m6 4v6',
  sun:'M12 3V1m0 22v-2M3 12H1m22 0h-2M5.6 5.6 4.2 4.2m15.6 15.6-1.4-1.4m0-12.8 1.4-1.4M4.2 19.8l1.4-1.4M17 12a5 5 0 1 1-10 0 5 5 0 0 1 10 0',
  moon:'M20.5 13A9 9 0 0 1 11 3.5 9 9 0 1 0 20.5 13Z',
  chevron:'m9 5 7 7-7 7', arrow:'M5 12h14m-5-5 5 5-5 5', back:'M19 12H5m5-5-5 5 5 5',
  chip:'M7 7h10v10H7ZM9 1v6m6-6v6M9 17v6m6-6v6M1 9h6m-6 6h6m10-6h6m-6 6h6',
  sparkle:'m12 3 2.4 6.6L21 12l-6.6 2.4L12 21l-2.4-6.6L3 12l6.6-2.4L12 3Zm7-1v4m-2-2h4',
  shield:'m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Zm-4 9 3 3 5-6',
  keyboard:'M3 5h18v14H3ZM6 9h1m4 0h1m4 0h1M6 12h1m4 0h1m4 0h1m-9 3h8',
  copy:'M9 9h12v12H9ZM15 5V3H3v12h2', check:'m5 12 4 4L19 6',
  file:'M14 2H4v20h16V8l-6-6Zm0 0v6h6M8 12h8m-8 4h6',
  headphones:'M3 14v-2a9 9 0 0 1 18 0v2M3 12h3v8H3Zm15 0h3v8h-3Z',
  globe:'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM3 12h18M12 3c5 5 5 13 0 18-5-5-5-13 0-18',
  lock:'M5 10h14v11H5ZM8 10V6a4 4 0 0 1 8 0v4m-4 5v2',
  info:'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM12 11v6m0-10v.1',
  warning:'m12 3 10 18H2L12 3Zm0 6v5m0 3v.1',
  stop:'M6 6h12v12H6Z', x:'m6 6 12 12M6 18 18 6',
  plus:'M12 5v14M5 12h14', search:'M16 10a6 6 0 1 1-12 0 6 6 0 0 1 12 0Zm-2 4 6 6',
  trash:'M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7',
  edit:'m14 5 5 5M4 20l5-1L21 7l-5-5L4 14v6Z',
  monitor:'M2 3h20v14H2ZM12 17v4m-5 0h10', download:'M12 3v12m-5-5 5 5 5-5M4 15v6h16v-6',
  upload:'M12 16V4m-5 5 5-5 5 5M4 16v5h16v-5',
  refresh:'M20 8a8 8 0 0 0-14-3L3 8m0-5v5h5m-4 8a8 8 0 0 0 14 3l3-3m0 5v-5h-5',
  palette:'M12 3a9 9 0 1 0 0 18c3 0 1-4 3-5 1-1 6 1 6-4a9 9 0 0 0-9-9ZM7 10h.1M10 7h.1M15 7h.1M17 11h.1',
  clock:'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM12 7v5l3 2',
};
const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name] || paths.file}"/></svg>`;
const escapeHTML = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const seedHistory = [
  {id:'sample-1',title:'A thought for the next design review',raw:'Hey, um, for the next design review, let’s keep the interface simple. I think we should give the important things more space and, you know, let the details get out of the way.',clean:'For the next design review, let’s keep the interface simple. Give the important things more space, and let the details get out of the way.',time:'10:42 AM',duration:'24 sec',app:'Notes'},
  {id:'sample-2',title:'A quick update for the team',raw:'Hey team, um, I’ve finished the first pass on the new workspace. Can we, uh, find a time to walk through it together tomorrow?',clean:'Hey team, I’ve finished the first pass on the new workspace. Can we find a time to walk through it together tomorrow?',time:'10:18 AM',duration:'18 sec',app:'Slack'},
  {id:'sample-3',title:'An idea worth coming back to',raw:'Remind me to, uh, explore a smaller recording overlay. Something that stays out of the way but, you know, still feels easy to find.',clean:'Explore a smaller recording overlay. Something that stays out of the way but still feels easy to find.',time:'9:56 AM',duration:'16 sec',app:'Notes'},
];
const defaultSettings = {theme:'light',mode:'toggle',mic:'Built-in microphone',shortcut:'Ctrl + Shift + Space',cleanup:true,local:true,motion:false,history:true,stt:'Whisper · Large v3 Turbo',model:'Qwen · 2.5 3B',instructions:'Remove filler words and repeated phrases. Fix punctuation and capitalization. Keep my meaning and natural tone. Do not add new information.'};
let storageAvailable=true;
function load(key,fallback){try{const value=localStorage.getItem('wispr_codex_'+key);return value?JSON.parse(value):structuredClone(fallback);}catch{storageAvailable=false;return structuredClone(fallback);}}
const savedSettings=load('settings',{});
let settings={...defaultSettings,...(savedSettings && typeof savedSettings==='object' && !Array.isArray(savedSettings)?savedSettings:{})};
let history=load('history',seedHistory);
if(!Array.isArray(history)||!history.every(h=>h&&['id','title','raw','clean','time','duration','app'].every(k=>typeof h[k]==='string'))) history=structuredClone(seedHistory);
let dictionary=load('dictionary',[{id:'word-1',word:'Wispr',sounds:'whisper'},{id:'word-2',word:'Injun',sounds:'in june'},{id:'word-3',word:'PostgreSQL',sounds:'post gres Q L'},{id:'word-4',word:'Cognee',sounds:'cog knee'}]);
if(!Array.isArray(dictionary)||!dictionary.every(w=>w&&['id','word','sounds'].every(k=>typeof w[k]==='string'))) dictionary=[];
let page='workspace', settingPage='recording', recordState='ready', transcriptTab='clean', current=history[0]||null;
let seconds=0,recordInterval,processTimeout,micTimeout,toastTimeout,previousFocus;
let hudComplete=false,hudTimeout;
let micTesting=false,modelBusy=null,modelResult={},searchQuery='';
const app=document.querySelector('#app'),dialog=document.querySelector('#dialog');
const settingsPages=[['recording','mic','Recording'],['models','chip','Models'],['cleanup','sparkle','Text cleanup'],['appearance','palette','Appearance'],['privacy','shield','Privacy & history']];
function save(key,value){try{localStorage.setItem('wispr_codex_'+key,JSON.stringify(value));}catch{storageAvailable=false;toast('Storage unavailable. Changes last for this session.','warning');}}
function applyTheme(){document.documentElement.dataset.theme=settings.theme==='dark'?'dark':'light';document.documentElement.dataset.motion=settings.motion?'reduced':'normal';}
function button(action,label,ico,style='ghost',extra=''){return `<button type="button" class="${style}" data-action="${action}" ${extra}>${ico?icon(ico):''}${label}</button>`;}
function pill(label,color='green',ico){return `<span class="pill ${color}">${ico?icon(ico):'<span class="dot"></span>'}${label}</span>`;}
function toggle(key,label){return `<button type="button" class="switch" role="switch" aria-checked="${Boolean(settings[key])}" aria-label="${label}" data-toggle="${key}"></button>`;}
function select(id,label,options,value){return `<select id="${id}" aria-label="${label}" data-setting="${id}">${options.map(o=>`<option ${o===value?'selected':''}>${escapeHTML(o)}</option>`).join('')}</select>`;}
function notice(text,type='info'){return `<div class="notice ${type}" role="${type==='error'?'alert':'status'}">${icon(type==='warning'?'warning':type==='success'?'check':'info')}<span>${text}</span></div>`;}
function navigate(next,sub){page=next;if(sub)settingPage=sub;searchQuery='';render();document.querySelector('#main').focus({preventScroll:true});}
function render(){
  applyTheme();
  const title=page==='settings'?settingsPages.find(x=>x[0]===settingPage)[2]:({workspace:'Dictation',history:'Recent history',dictionary:'Dictionary'}[page]);
  app.innerHTML=`<header class="topbar"><div class="brand"><div class="brand-mark">${icon('wave')}</div><div><div class="brand-word">wispr<span style="color:var(--primary)">.</span></div><div class="brand-sub">Voice workspace</div></div></div>
    <nav class="topnav" aria-label="Main navigation">${[['workspace','home','Workspace'],['history','history','History'],['dictionary','book','Dictionary']].map(([p,i,l])=>button('navigate',l,i,`nav-btn ${page===p?'active':''}`,`data-page="${p}" ${page===p?'aria-current="page"':''}`)).join('')}</nav>
    <div class="top-actions">${button('theme',settings.theme==='dark'?'Dark':'Light',settings.theme==='dark'?'moon':'sun','ghost','aria-label="Toggle color theme"')}
    <span class="divider-v"></span>${button('navigate','Settings','settings',`nav-btn ${page==='settings'?'active':''}`,'data-page="settings" '+(page==='settings'?'aria-current="page"':''))}<span class="avatar" aria-label="Demo profile">IN</span></div></header>
    <div class="app-body">${page==='settings'?sidebar():''}<main class="content" id="main" tabindex="-1">
    <div class="breadcrumb"><div class="row">${icon(page==='settings'?'settings':'home')}<span>${page==='settings'?'Settings':'Personal workspace'}</span><span class="crumb-sep">/</span><span style="color:var(--text)">${title}</span></div><div class="row">${pill('Demo environment','purple')}${settings.local?`${icon('shield')}<span>Local mode</span>`:`${icon('globe')}<span>Cloud mode · simulated</span>`}</div></div>
    <div class="main-inner ${page==='settings'?'settings-inner':''}">${page==='workspace'?workspace():page==='settings'?settingsView():page==='history'?historyView():dictionaryView()}</div></main></div>
    <footer class="footer"><div class="row footer-left">${icon('wave')}<span>Interactive concept</span><span class="divider-v"></span><span>Sample data · no audio captured</span></div><div class="row">${button('preview-hud','Preview HUD','wave')}${button('states','Preview states','palette')}${button('shortcuts','Keyboard shortcuts','keyboard')}<span class="divider-v"></span><span>DESIGN 01 / CODEX</span></div></footer>`;
  renderHud();
}
function sidebar(){return `<aside class="sidebar" aria-label="Settings navigation">${button('navigate','Back to workspace','back','ghost back','data-page="workspace"')}<div class="sidebar-title">Make it yours.</div><div class="eyebrow">Preferences</div><nav>${settingsPages.map(([p,i,l])=>button('setting-page',l,i,`nav-btn ${settingPage===p?'active':''}`,`data-page="${p}" ${settingPage===p?'aria-current="page"':''}`)).join('')}</nav></aside>`;}
function workspace(){return `<div class="page-heading between"><div><div class="eyebrow">A little less typing. A little more flow.</div><h1>Your voice, in writing.</h1><p>Start a dictation. Keep your train of thought.</p></div><span class="heading-side pill">${icon('monitor')}Desktop workspace</span></div>
    ${recordState==='warning'?`<div class="preview-alert">${notice('Microphone input is quiet. Move closer or choose another device. <strong>Simulated warning.</strong>','warning')}</div>`:''}
    ${recordState==='error'?`<div class="preview-alert">${notice('The microphone is unavailable. Your previous transcript is safe. <strong>Simulated error.</strong>','error')}</div>`:''}
    <div class="hero-grid">${recorder()}<section class="card setup-card" aria-label="Current setup"><div class="between"><h2 class="setup-title">Your setup</h2>${pill('Demo','purple')}</div>
    <div class="setup-row">${icon('mic')}<div>Audio input<strong>${escapeHTML(settings.mic)}</strong></div></div>
    <div class="setup-row">${icon('chip')}<div>Speech model<strong>${escapeHTML(settings.stt.split(' · ')[0])}<span style="color:var(--muted);font-weight:400"> / ${escapeHTML(settings.stt.split(' · ')[1]||'')}</span></strong></div></div>
    <div class="setup-row">${icon('sparkle')}<div>Text cleanup<strong>${settings.cleanup?'A little polish. Still you.':'Keep your original words'}</strong></div>${pill(settings.cleanup?'On':'Off',settings.cleanup?'purple':'')}</div>
    <div class="setup-foot">${button('navigate','Adjust settings','settings','ghost','data-page="settings"')}<span class="row small muted">${icon('chevron')}</span></div></section></div>
    <div class="section-heading"><h2>Latest dictation</h2><span class="small muted">${current?`${icon('clock')} <span>${escapeHTML(current.time)}</span>`:'Ready when you are'}</span></div>
    ${current?transcript():`<div class="card empty">${icon('file')}<h2>A blank page, without the typing.</h2><p>Start the demo above to see your first transcript here.</p></div>`}
    <div class="section-heading"><h2>Recent activity <span class="muted" style="font-weight:400;font-size:11px;margin-left:7px">Sample history</span></h2>${button('navigate','View history','arrow','ghost accent','data-page="history"')}</div>
    <div class="card history-list">${history.slice(current?.id===history[0]?.id?1:0,3).map(historyRow).join('')||'<div class="empty"><p>Your next dictation will appear here.</p></div>'}</div>`;}
function recorder(){
  const active=recordState==='recording',busy=recordState==='processing',error=recordState==='error';
  const labels={ready:'Ready when you are',recording:'Listening · simulated',processing:'Polishing your words',warning:'Low input level',error:'Microphone unavailable'};
  const heights=[12,18,24,17,28,39,25,43,53,36,58,73,51,67,87,62,79,57,88,69,47,73,53,38,59,41,28,44,26,34,19,24,14];
  return `<section class="card record-card ${recordState}" aria-label="Dictation recorder"><div class="record-top"><span class="state-label small" id="record-status" role="status">${active?'<span class="pending-dot"></span>':busy?'<span class="spinner"></span>':icon(error?'warning':'wave')}${labels[recordState]}</span><span class="eyebrow">${active?'<span class="recording-timer" id="timer">'+formatTime(seconds)+'</span>':'TRY IT OUT'}</span></div>
  <div class="waveform ${active||busy?'live':''}" aria-hidden="true">${heights.map((h,i)=>`<span style="--h:${h}px;--d:${-i*.13}s"></span>`).join('')}</div><div class="record-caption">${active?'Your ideas have the floor.':busy?'A moment to make it read naturally.':error?'Reconnect, then try again.':'From a passing thought to the perfect words.'}</div>
  ${button(error?'recover':'record',active?'Finish dictation':busy?'Processing…':error?'Try again':'Start dictation',active?'stop':busy?null:error?'refresh':'mic','btn primary record-btn',busy?'disabled':'')}
  <div class="record-hint">${active?'Click to finish, or press <kbd>Esc</kbd> to cancel':busy?'Simulated transcription and cleanup':`or ${settings.mode==='hold'?'hold':'press'} <kbd>${escapeHTML(settings.shortcut)}</kbd>`}</div>${active?button('cancel-record','Cancel',null,'ghost cancel-record'):''}</section>`;
}
function transcript(){const text=transcriptTab==='clean'?current.clean:current.raw;return `<section class="card transcript-card"><div class="transcript-toolbar"><div class="segment" role="group" aria-label="Transcript version">${button('transcript-tab','Polished','sparkle',transcriptTab==='clean'?'selected accent':'','data-tab="clean" aria-pressed="'+(transcriptTab==='clean')+'"')}${button('transcript-tab','Original',null,transcriptTab==='raw'?'selected':'','data-tab="raw" aria-pressed="'+(transcriptTab==='raw')+'"')}</div>${pill('Sample transcript','', 'file')}</div><p class="transcript-body">${escapeHTML(text)}</p><div class="transcript-foot"><span>${text.trim().split(/\s+/).length} words<span class="meta-dot">·</span>${escapeHTML(current.duration)}<span class="meta-dot">·</span>${transcriptTab==='clean'?'Ready to copy':'Original speech'}</span>${button('copy-current','Copy text','copy','ghost')}</div></section>`;}
function historyRow(h){return `<div class="history-row"><span class="history-symbol">${icon(h.app==='Slack'?'globe':'file')}</span><button class="history-main" data-action="open-history" data-id="${escapeHTML(h.id)}"><strong>${escapeHTML(h.title)}</strong><small>${escapeHTML(h.app)}<span class="meta-dot">·</span>${escapeHTML(h.duration)}<span class="meta-dot">·</span>Sample dictation</small></button><time>${escapeHTML(h.time)}</time>${button('copy-history','', 'copy','ghost icon-button copy-row',`data-id="${escapeHTML(h.id)}" aria-label="Copy ${escapeHTML(h.title)}"`)}${page==='history'?button('delete-history','', 'trash','ghost icon-button',`data-id="${escapeHTML(h.id)}" aria-label="Delete ${escapeHTML(h.title)}"`):''}</div>`;}
function historyView(){const filtered=history.filter(h=>(h.title+' '+h.clean+' '+h.raw).toLowerCase().includes(searchQuery.toLowerCase()));return `<div class="page-heading"><div class="eyebrow">Nothing lost along the way</div><h1>Recent history</h1><p>Your words, ready to pick up where you left off.</p></div>${!settings.history?notice('Saving history is paused. New demo dictations will only appear in the workspace.'):''}<div class="list-toolbar"><div class="searchbar">${icon('search')}<input type="search" id="history-search" aria-label="Search dictations" placeholder="Search your dictations…" value="${escapeHTML(searchQuery)}"></div><span class="small muted">${history.length} dictations</span></div><div id="history-results">${historyResults(filtered)}</div>`;}
function historyResults(filtered){return `<div class="list-label">Sample sessions</div><div class="card history-list">${filtered.length?filtered.map(historyRow).join(''):`<div class="empty">${icon('history')}<h2>${searchQuery?'No matching dictations':'A fresh start.'}</h2><p>${searchQuery?'Try another word or phrase.':'Your saved demo dictations will appear here.'}</p></div>`}</div>`;}
function dictionaryView(){return `<div class="page-heading between"><div><div class="eyebrow">Sounds like you. Spelled like you.</div><h1>Your dictionary</h1><p>A home for names, technical terms, and words you use every day.</p></div>${button('add-word','Add a word','plus','btn primary')}</div>${notice('A small detail that makes a difference. Add a preferred spelling and, optionally, how it sounds.')}<div class="list-toolbar"><div class="searchbar">${icon('search')}<input type="search" id="dictionary-search" aria-label="Search dictionary" placeholder="Find a word…" value="${escapeHTML(searchQuery)}"></div><div class="row">${button('import-words','Import','upload')}${button('export-words','Export','download','ghost',dictionary.length?'':'disabled')}</div></div><div id="dictionary-results">${dictionaryResults()}</div><p class="dictionary-foot">${dictionary.length} personal words · Saved in this browser for the demo.</p><input type="file" id="dictionary-import" accept="application/json,.json" hidden>`;}
function dictionaryResults(){const words=dictionary.filter(w=>(w.word+' '+w.sounds).toLowerCase().includes(searchQuery.toLowerCase()));return `<div class="card table-wrap">${words.length?`<table class="dictionary-table"><thead><tr><th>Preferred spelling</th><th>Sounds like</th><th><span class="muted">Actions</span></th></tr></thead><tbody>${words.map(w=>`<tr><td><strong>${escapeHTML(w.word)}</strong></td><td class="muted">${escapeHTML(w.sounds||'—')}</td><td>${button('edit-word','','edit','ghost icon-button',`data-id="${escapeHTML(w.id)}" aria-label="Edit ${escapeHTML(w.word)}"`)}${button('delete-word','','trash','ghost icon-button',`data-id="${escapeHTML(w.id)}" aria-label="Delete ${escapeHTML(w.word)}"`)}</td></tr>`).join('')}</tbody></table>`:`<div class="empty">${icon('book')}<h2>${searchQuery?'No matching words':'Make it your vocabulary.'}</h2><p>${searchQuery?'Try another spelling.':'Add your first name or a word you use often.'}</p></div>`}</div>`;}
function settingRow(label,description,control,forId){return `<div class="setting-row"><div class="setting-label">${forId?`<label for="${forId}">${label}</label>`:`<strong>${label}</strong>`}<p>${description}</p></div>${control}</div>`;}
function settingsView(){let html='';
  if(settingPage==='recording')html=`<div class="page-heading"><div class="eyebrow">Preferences / 01</div><h1>Recording</h1><p>A natural start. A clean finish. Set up how you speak.</p></div><section class="settings-section"><h2>Audio input</h2><div class="card">${settingRow('Microphone','Choose the input used for your dictations.',select('mic','Microphone',['Built-in microphone','USB microphone','Studio display microphone'],settings.mic),'mic')}${settingRow('Make sure you sound clear','Preview the microphone level animation. No audio is captured.',button('test-mic',micTesting?'Stop preview':'Test microphone',micTesting?'stop':'mic','btn'))}<div class="setting-row"><div class="grow"><div class="between small"><span class="muted">Input level · simulated</span><span style="color:var(--green)">${micTesting?'Receiving sample audio':'Waiting for a test'}</span></div><div class="meter ${micTesting?'running':''}">${Array.from({length:38},(_,i)=>`<i style="--i:${i}"></i>`).join('')}</div></div></div></div></section><section class="settings-section"><h2>How you record</h2><div class="card">${settingRow('Recording mode','Use the shortcut below while this demo tab has focus.',`<div class="segment" role="group" aria-label="Recording mode">${button('mode','Press to toggle',null,settings.mode==='toggle'?'selected':'','data-mode="toggle" aria-pressed="'+(settings.mode==='toggle')+'"')}${button('mode','Hold to talk',null,settings.mode==='hold'?'selected':'','data-mode="hold" aria-pressed="'+(settings.mode==='hold')+'"')}</div>`)}${settingRow('Dictation shortcut','Start and finish a dictation from this browser tab.',select('shortcut','Dictation shortcut',['Ctrl + Shift + Space','Alt + Shift + D'],settings.shortcut),'shortcut')}${settingRow('Cancel recording','Discard the current recording before processing.','<kbd>Esc</kbd>')}</div></section>${notice('Shortcuts work within this demo tab. System-wide shortcuts and microphone access belong to the desktop app.')}`;
  if(settingPage==='models')html=`<div class="page-heading"><div class="eyebrow">Preferences / 02</div><h1>Models</h1><p>Two small steps between your voice and the right words.</p></div><div class="card">${settingRow('Keep processing local','Prefer on-device models for speech and cleanup.',toggle('local','Keep processing local'))}</div><section class="settings-section"><h2>Your voice pipeline</h2>${modelCard('stt','mic','Speech to text','Turns your voice into a first draft.',['Whisper · Large v3 Turbo','Whisper · Small'])}${modelCard('model','sparkle','Text cleanup','Adds punctuation and removes the little hesitations.',['Qwen · 2.5 3B','Qwen · 2.5 7B'])}</section>${notice('Model selections and connection tests are simulated. No models are downloaded or run in this demo.')}`;
  if(settingPage==='cleanup')html=`<div class="page-heading"><div class="eyebrow">Preferences / 03</div><h1>Text cleanup</h1><p>Your meaning, with a little breathing room.</p></div><div class="card">${settingRow('Polish after dictation','Clean up filler words while keeping your natural voice.',toggle('cleanup','Polish after dictation'))}</div><section class="settings-section"><h2>A little guidance</h2><div class="card instruction-wrap"><label for="instructions">Cleanup instructions</label><textarea id="instructions" ${settings.cleanup?'':'disabled'}>${escapeHTML(settings.instructions)}</textarea><div class="instruction-actions"><span class="small muted">Saved as a preference; not sent to a model.</span>${button('save-instructions','Save instructions','check','btn',settings.cleanup?'':'disabled')}</div></div></section><section class="settings-section"><div class="between"><h2>See the difference</h2>${button('cleanup-preview','Preview example','sparkle','ghost accent',settings.cleanup?'':'disabled')}</div><div class="comparison"><div><div class="eyebrow">Original</div>“So, um, let’s move the design review to Thursday. And, uh, bring the new mockups.”</div><div class="cleaned-example"><div class="eyebrow">Polished · sample</div><span id="cleanup-example">${settings.cleanup?'Let’s move the design review to Thursday. Bring the new mockups.':'Enable cleanup to preview polished text.'}</span></div></div></section>${notice('This is a fixed before-and-after example. Edited instructions are saved, but do not change the simulated output.')}`;
  if(settingPage==='appearance')html=`<div class="page-heading"><div class="eyebrow">Preferences / 04</div><h1>Appearance</h1><p>A comfortable place for your thoughts, day or night.</p></div><section class="settings-section"><h2>Color theme</h2><div class="card"><div class="themes">${['light','dark'].map(t=>`<button class="theme-choice" data-action="set-theme" data-theme="${t}" aria-pressed="${settings.theme===t}"><div class="mini-window ${t}"></div><span>${icon(t==='light'?'sun':'moon')}${t==='light'?'Light':'Dark'}${settings.theme===t?icon('check'):''}</span></button>`).join('')}</div><div class="theme-note">Soft neutrals. One plum accent. The same familiar space.</div></div></section><section class="settings-section"><h2>Motion</h2><div class="card">${settingRow('Reduce motion','Keep transitions still. Your system preference is also respected.',toggle('motion','Reduce motion'))}</div></section><section class="settings-section"><h2>Typography</h2><div class="card">${settingRow('Geist','Interface text · 12–15 px · Regular and medium weights.','<span style="font-size:25px;letter-spacing:-1px">Aa</span>')}${settingRow('Monospace','Keyboard shortcuts and recording times.','<kbd>Ctrl + Shift + Space</kbd>')}</div></section>`;
  if(settingPage==='privacy')html=`<div class="page-heading"><div class="eyebrow">Preferences / 05</div><h1>Privacy & history</h1><p>Keep what’s useful. Clear what isn’t.</p></div>${notice('This prototype never captures audio or contacts an AI service. Demo preferences, words, and sample history stay in this browser.')}<section class="settings-section"><h2>Recent history</h2><div class="card">${settingRow('Save dictation history','Keep future sample dictations in your recent history.',toggle('history','Save dictation history'))}${settingRow('Clear recent history',`${history.length} saved sample dictations. Dictionary and settings stay unchanged.`,button('clear-history','Clear history','trash','btn danger',history.length?'':'disabled'))}</div></section><section class="settings-section"><h2>Demo data</h2><div class="card">${settingRow('Restore sample data','Restore the example history and dictionary for another review.',button('restore','Restore samples','refresh','btn'))}</div></section>`;
  return html+`<div class="settings-footer">${icon(storageAvailable?'check':'warning')}${storageAvailable?'Preferences saved in this browser':'Storage unavailable · preferences last for this session'}</div>`;
}
function modelCard(key,ico,title,subtitle,options){const busy=modelBusy===key;return `<div class="card model-card"><div class="between"><div class="row"><div class="model-icon">${icon(ico)}</div><div><h3>${title}</h3><span class="small muted">${subtitle}</span></div></div>${busy?pill('Testing…','blue'):pill(modelResult[key]||'Ready · demo','green')}</div><div class="model-select">${select(key,title+' model',options,settings[key])}${button('test-model',busy?'Testing…':'Test model',busy?null:'wave','btn',`data-key="${key}" ${modelBusy?'disabled':''}`)}</div><p class="model-meta">${settings.local?'On-device':'Cloud preference'}<span class="meta-dot">·</span>Simulated model configuration</p></div>`;}
function toast(message,ico='check'){clearTimeout(toastTimeout);const element=document.querySelector('#toast');element.innerHTML=icon(ico)+escapeHTML(message);element.classList.add('visible');toastTimeout=setTimeout(()=>element.classList.remove('visible'),3400);}
function openDialog(content){previousFocus=document.activeElement;dialog.innerHTML=button('close-dialog','','x','ghost icon-button dialog-close','aria-label="Close dialog"')+content;dialog.showModal();}
function closeDialog(){dialog.close();if(previousFocus?.isConnected)previousFocus.focus();}
dialog.addEventListener('cancel',()=>{setTimeout(()=>{if(previousFocus?.isConnected)previousFocus.focus();},0);});
dialog.addEventListener('click',e=>{if(e.target===dialog){const rect=dialog.getBoundingClientRect();if(e.clientX<rect.left||e.clientX>rect.right||e.clientY<rect.top||e.clientY>rect.bottom)closeDialog();}});
async function copy(text){try{await navigator.clipboard.writeText(text);toast('Copied. Ready wherever you need it.');}catch{openDialog(`<h2 id="dialog-title">Copy your text</h2><p>Clipboard access isn’t available here. Select the text and copy it manually.</p><textarea aria-label="Text to copy" readonly>${escapeHTML(text)}</textarea>`);dialog.querySelector('textarea').select();}}
function formatTime(n){return `${Math.floor(n/60).toString().padStart(2,'0')}:${(n%60).toString().padStart(2,'0')}`;}
function resetHud(){clearTimeout(hudTimeout);hudComplete=false;}
function dismissHud(){
  const hadFocus=document.querySelector('#hud-root').contains(document.activeElement);
  resetHud();
  if(recordState==='warning'||recordState==='error'){recordState='ready';render();}else renderHud();
  if(hadFocus){const destination=document.querySelector('.record-btn')||document.querySelector('#main');destination?.focus({preventScroll:true});}
}
function renderHud(){
  const root=document.querySelector('#hud-root');
  const state=hudComplete?'complete':recordState;
  const visible=state!=='ready';
  document.body.classList.toggle('hud-visible',visible);
  if(!visible){root.innerHTML='';return;}
  const content={
    recording:['Listening','Speak naturally · demo','mic'],
    processing:['Polishing','Preparing sample text','sparkle'],
    complete:['Text is ready','Sample transcript · copy to use','check'],
    warning:['A little quiet','Check your microphone · demo','warning'],
    error:['Input unavailable','Reconnect to try again · demo','warning'],
  }[state];
  const heights=[8,14,21,12,27,19,32,23,15,28,18,10,17];
  const actions=state==='recording'
    ?button('hud-finish','Finish','stop','btn primary')+button('hud-cancel','Cancel','x','ghost')
    :state==='processing'
      ?button('hud-finish','Working',null,'btn','disabled')+button('hud-cancel','Cancel','x','ghost')
      :state==='complete'
        ?button('hud-copy','Copy','copy','btn primary')+button('hud-dismiss','Close','x','ghost')
        :button('hud-recover','Try again','refresh','btn')+button('hud-dismiss','Close','x','ghost');
  root.innerHTML=`<section class="dictation-hud ${state}" role="region" aria-label="Dictation HUD">
    <span class="hud-symbol">${state==='processing'?'<span class="spinner"></span>':icon(content[2])}</span>
    <div class="hud-message" role="status" aria-live="polite" aria-atomic="true"><strong>${content[0]}</strong><small>${content[1]}</small></div>
    ${state==='recording'?`<div class="hud-wave" aria-hidden="true">${heights.map((h,i)=>`<i style="--h:${h}px;--d:${i*-.12}s"></i>`).join('')}</div><span class="hud-timer" id="hud-timer" aria-label="Elapsed recording time">${formatTime(seconds)}</span>`:'<div class="hud-spacer"></div>'}
    <div class="hud-actions">${actions}</div>
  </section>`;
}
function startRecording(){resetHud();clearTimeout(processTimeout);clearInterval(recordInterval);recordState='recording';seconds=0;page='workspace';render();focusRecord();recordInterval=setInterval(()=>{seconds++;const timer=document.querySelector('#timer');if(timer)timer.textContent=formatTime(seconds);const hudTimer=document.querySelector('#hud-timer');if(hudTimer)hudTimer.textContent=formatTime(seconds);if(seconds>=120)finishRecording();},1000);}
function focusRecord(){document.querySelector('.record-btn')?.focus({preventScroll:true});}
function finishRecording(){if(recordState!=='recording')return;clearInterval(recordInterval);recordState='processing';render();processTimeout=setTimeout(()=>{
  const sample=seedHistory[0];current={...sample,id:'dictation-'+Date.now(),time:new Date().toLocaleTimeString([],{hour:'numeric',minute:'2-digit'}),duration:`${Math.max(seconds,1)} sec`,title:'A thought for the next design review',clean:settings.cleanup?sample.clean:sample.raw};
  if(settings.history){history.unshift(current);save('history',history);}recordState='ready';hudComplete=true;transcriptTab=settings.cleanup?'clean':'raw';render();hudTimeout=setTimeout(dismissHud,5000);focusRecord();toast('Sample dictation is ready to review.');
},1700);}
function cancelRecording(){resetHud();clearInterval(recordInterval);clearTimeout(processTimeout);recordState='ready';render();focusRecord();toast('Recording canceled. Nothing was added.');}
function wordDialog(id){const word=dictionary.find(w=>w.id===id);openDialog(`<h2 id="dialog-title">${word?'Edit a word':'Make it your word.'}</h2><p>A preferred spelling helps your voice feel more like you.</p><form id="word-form" data-id="${word?escapeHTML(word.id):''}"><label for="word">Preferred spelling</label><input id="word" name="word" type="text" maxlength="80" required placeholder="e.g. PostgreSQL" value="${escapeHTML(word?.word||'')}"><label for="sounds">Sounds like <span class="muted">(optional)</span></label><input id="sounds" name="sounds" type="text" maxlength="120" placeholder="e.g. post gres Q L" value="${escapeHTML(word?.sounds||'')}"><div class="error-text" id="word-error" role="alert"></div><div class="dialog-actions">${button('close-dialog','Cancel',null,'btn')}<button type="submit" class="btn primary">${icon('check')}${word?'Save changes':'Add word'}</button></div></form>`);dialog.querySelector('#word').focus();}
function confirmDialog(title,description,action,id,label='Delete'){openDialog(`<h2 id="dialog-title">${title}</h2><p>${description}</p><div class="dialog-actions">${button('close-dialog','Cancel',null,'btn')}${button(action,label,'trash','btn danger',id?`data-id="${escapeHTML(id)}"`:'')}</div>`);}
document.addEventListener('click',async e=>{
 const target=e.target.closest('button');if(!target||target.disabled)return;
 if(target.dataset.toggle){const key=target.dataset.toggle;settings[key]=!settings[key];save('settings',settings);render();document.querySelector(`[data-toggle="${key}"]`)?.focus({preventScroll:true});return;}
 const {action,id}=target.dataset;
 switch(action){
 case 'navigate':navigate(target.dataset.page);break;
 case 'setting-page':navigate('settings',target.dataset.page);break;
 case 'theme':case 'set-theme':settings.theme=action==='set-theme'?target.dataset.theme:settings.theme==='light'?'dark':'light';save('settings',settings);render();document.querySelector(action==='theme'?'[data-action="theme"]':`.theme-choice[data-theme="${settings.theme}"]`)?.focus({preventScroll:true});break;
 case 'preview-hud':startRecording();break;
 case 'hud-finish':finishRecording();document.querySelector('[data-action="hud-cancel"]')?.focus({preventScroll:true});break;
 case 'hud-cancel':cancelRecording();break;
 case 'hud-copy':if(current)await copy(current.clean);break;
 case 'hud-dismiss':dismissHud();break;
 case 'hud-recover':
 case 'recover':recordState='ready';resetHud();render();focusRecord();toast('Demo microphone reconnected.');break;
 case 'record':if(recordState==='recording')finishRecording();else if(recordState!=='processing')startRecording();break;
 case 'cancel-record':cancelRecording();break;
 case 'transcript-tab':transcriptTab=target.dataset.tab;render();document.querySelector(`[data-tab="${transcriptTab}"]`).focus({preventScroll:true});break;
 case 'copy-current':if(current)await copy(current[transcriptTab]);break;
 case 'copy-history':await copy(history.find(h=>h.id===id).clean);break;
 case 'open-history':{const h=history.find(h=>h.id===id);openDialog(`<h2 id="dialog-title">${escapeHTML(h.title)}</h2><p>${escapeHTML(h.time)} · ${escapeHTML(h.duration)} · Sample dictation</p><div class="eyebrow">Polished</div><div class="text-block">${escapeHTML(h.clean)}</div><details style="margin-top:17px;font-size:12px"><summary>Original transcript</summary><div class="text-block">${escapeHTML(h.raw)}</div></details><div class="dialog-actions">${button('copy-history','Copy text','copy','btn primary',`data-id="${escapeHTML(id)}"`)}</div>`);break;}
 case 'delete-history':confirmDialog('Delete this dictation?','This removes this sample from your local history.','confirm-delete-history',id);break;
 case 'confirm-delete-history':history=history.filter(h=>h.id!==id);if(current?.id===id)current=history[0]||null;save('history',history);closeDialog();render();toast('Dictation deleted.');break;
 case 'add-word':wordDialog();break;
 case 'edit-word':wordDialog(id);break;
 case 'delete-word':confirmDialog('Remove this word?',`“${escapeHTML(dictionary.find(w=>w.id===id).word)}” will be removed from your dictionary.`,'confirm-delete-word',id,'Remove word');break;
 case 'confirm-delete-word':dictionary=dictionary.filter(w=>w.id!==id);save('dictionary',dictionary);closeDialog();render();toast('Word removed.');break;
 case 'import-words':document.querySelector('#dictionary-import').click();break;
 case 'export-words':{const blob=new Blob([JSON.stringify(dictionary.map(({word,sounds})=>({word,sounds})),null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='dictionary_codex.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('Dictionary exported.');break;}
 case 'mode':settings.mode=target.dataset.mode;save('settings',settings);render();document.querySelector(`[data-mode="${settings.mode}"]`).focus({preventScroll:true});break;
 case 'test-mic':micTesting=!micTesting;clearTimeout(micTimeout);render();if(micTesting)micTimeout=setTimeout(()=>{micTesting=false;if(page==='settings'&&settingPage==='recording')render();toast('Microphone animation preview complete.');},6000);break;
 case 'test-model':{const key=target.dataset.key;modelBusy=key;render();setTimeout(()=>{modelBusy=null;modelResult[key]='Test passed · demo';if(page==='settings'&&settingPage==='models')render();toast('Simulated model test complete.');},1300);break;}
 case 'save-instructions':settings.instructions=document.querySelector('#instructions').value.trim()||defaultSettings.instructions;save('settings',settings);toast('Cleanup instructions saved for the demo.');break;
 case 'cleanup-preview':{const el=document.querySelector('#cleanup-example');el.innerHTML='<span class="spinner"></span> Polishing the sample…';target.disabled=true;setTimeout(()=>{if(el.isConnected){el.textContent='Let’s move the design review to Thursday. Bring the new mockups.';target.disabled=false;}},1000);break;}
 case 'clear-history':confirmDialog('Clear recent history?','All sample dictations in this browser will be removed. Your dictionary and preferences will stay.','confirm-clear',null,'Clear history');break;
 case 'confirm-clear':history=[];current=null;save('history',history);closeDialog();render();toast('History cleared. A fresh start.');break;
 case 'restore':confirmDialog('Restore the examples?','This replaces your current demo history and dictionary with the original sample data.','confirm-restore',null,'Restore samples');break;
 case 'confirm-restore':history=structuredClone(seedHistory);dictionary=[{id:'word-1',word:'Wispr',sounds:'whisper'},{id:'word-2',word:'Injun',sounds:'in june'},{id:'word-3',word:'PostgreSQL',sounds:'post gres Q L'},{id:'word-4',word:'Cognee',sounds:'cog knee'}];current=history[0];save('history',history);save('dictionary',dictionary);closeDialog();render();toast('Sample data restored.');break;
 case 'states':openDialog(`<h2 id="dialog-title">A feel for every state.</h2><p>Preview feedback in the workspace. All states are simulated. Hover or Tab through controls to inspect their interaction states.</p><div class="state-grid">${[['ready','wave','Ready'],['recording','mic','Recording'],['processing','refresh','Processing'],['warning','warning','Low input'],['error','warning','Unavailable'],['empty','file','Empty transcript']].map(([state,ico,label])=>button('preview-state',label,ico,'btn',`data-state="${state}"`)).join('')}</div><div style="margin-top:20px" class="row">${button('none','Disabled action','download','btn','disabled')}<span class="small muted">Unavailable action</span></div>`);break;
 case 'preview-state':{resetHud();closeDialog();clearInterval(recordInterval);clearTimeout(processTimeout);const state=target.dataset.state;page='workspace';recordState=state==='empty'?'ready':state;if(state==='empty')current=null;if(state==='recording')startRecording();else{render();if(state==='processing')processTimeout=setTimeout(()=>{recordState='ready';render();toast('Processing preview complete.');},3500);}document.querySelector('#main')?.focus({preventScroll:true});break;}
 case 'shortcuts':openDialog(`<h2 id="dialog-title">Stay in your flow.</h2><p>Keyboard shortcuts work while this demo tab is focused.</p><div class="shortcuts-list"><span>${settings.mode==='hold'?'Hold to dictate':'Start / finish dictation'}</span><kbd>${escapeHTML(settings.shortcut)}</kbd><span>Cancel recording / close dialog</span><kbd>Esc</kbd><span>Open settings</span><kbd>Ctrl + ,</kbd><span>Move between controls</span><kbd>Tab</kbd></div>`);break;
 case 'close-dialog':closeDialog();break;
 }
});
document.addEventListener('submit',e=>{
 if(e.target.id!=='word-form')return;e.preventDefault();const id=e.target.dataset.id;const word=e.target.elements.word.value.trim(),sounds=e.target.elements.sounds.value.trim();
 const error=dialog.querySelector('#word-error');if(!word){error.textContent='Add a spelling to continue.';return;}if(dictionary.some(w=>w.id!==id&&w.word.toLowerCase()===word.toLowerCase())){error.textContent='This word is already in your dictionary.';return;}
 if(id)dictionary=dictionary.map(w=>w.id===id?{...w,word,sounds}:w);else dictionary.push({id:'word-'+Date.now(),word,sounds});save('dictionary',dictionary);closeDialog();render();toast(id?'Word updated.':'A new word, in your own words.');
});
document.addEventListener('input',e=>{if(e.target.id==='history-search'){searchQuery=e.target.value;document.querySelector('#history-results').innerHTML=historyResults(history.filter(h=>(h.title+' '+h.clean+' '+h.raw).toLowerCase().includes(searchQuery.toLowerCase())));}if(e.target.id==='dictionary-search'){searchQuery=e.target.value;document.querySelector('#dictionary-results').innerHTML=dictionaryResults();}});
document.addEventListener('change',async e=>{
 if(e.target.dataset.setting){settings[e.target.dataset.setting]=e.target.value;save('settings',settings);toast('Preference saved.');}
 if(e.target.id==='dictionary-import'){
  const file=e.target.files?.[0];if(!file)return;
  try{if(file.size>100000)throw new Error('Use a JSON file smaller than 100 KB.');const words=JSON.parse(await file.text());
   if(!Array.isArray(words)||words.length>500||!words.every(w=>w&&typeof w.word==='string'&&w.word.trim()&&w.word.length<=80&&(w.sounds===undefined||(typeof w.sounds==='string'&&w.sounds.length<=120))))throw new Error('Expected a JSON array of {"word": "spelling", "sounds": "optional"} entries (up to 500).');
   let added=0;words.forEach((w,i)=>{if(!dictionary.some(d=>d.word.toLowerCase()===w.word.trim().toLowerCase())){dictionary.push({id:`import-${Date.now()}-${i}`,word:w.word.trim(),sounds:(w.sounds||'').trim()});added++;}});save('dictionary',dictionary);render();toast(`${added} words imported. Duplicate spellings skipped.`);
  }catch(error){openDialog(`<h2 id="dialog-title">Couldn’t import these words</h2><p>${escapeHTML(error.message)}</p><div class="dialog-actions">${button('close-dialog','Got it',null,'btn primary')}</div>`);}finally{e.target.value='';}
 }
});
let holding=false;
function shortcutMatches(e){return settings.shortcut==='Alt + Shift + D'?e.altKey&&e.shiftKey&&e.code==='KeyD':e.ctrlKey&&e.shiftKey&&e.code==='Space';}
document.addEventListener('keydown',e=>{
 if(dialog.open&&e.key==='Tab'){
  const controls=[...dialog.querySelectorAll('button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), summary, [href], [tabindex="0"]')].filter(el=>el.getClientRects().length);
  const first=controls[0],last=controls.at(-1);
  if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}
  else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}
  return;
 }
 if(e.key==='Escape'&&!dialog.open&&(recordState==='recording'||recordState==='processing')){e.preventDefault();holding=false;cancelRecording();return;}
 if(dialog.open||e.target.matches('input,textarea,select,[contenteditable]'))return;
 if(e.ctrlKey&&e.key===','){e.preventDefault();navigate('settings');return;}
 if(shortcutMatches(e)){e.preventDefault();if(e.repeat||recordState==='processing')return;if(settings.mode==='hold'){holding=true;if(recordState!=='recording')startRecording();}else if(recordState==='recording')finishRecording();else startRecording();}
});
document.addEventListener('keyup',e=>{if(holding&&['Space','KeyD','ControlLeft','ControlRight','AltLeft','AltRight','ShiftLeft','ShiftRight'].includes(e.code)){holding=false;finishRecording();}});
window.addEventListener('blur',()=>{if(holding){holding=false;cancelRecording();}});
render();
