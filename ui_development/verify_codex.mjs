import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { mkdir, writeFile } from 'node:fs/promises';
const root=path.dirname(fileURLToPath(import.meta.url));
process.env.PLAYWRIGHT_BROWSERS_PATH=path.join(root,'.tools_codex/browsers');
const {chromium}=await import('./.tools_codex/node_modules/playwright/index.mjs');
const browser=await chromium.launch({headless:true,env:{...process.env,LD_LIBRARY_PATH:path.join(root,'.tools_codex/libs/usr/lib/x86_64-linux-gnu')}});
const context=await browser.newContext({viewport:{width:1440,height:1000},permissions:['clipboard-read','clipboard-write']});
const page=await context.newPage();
const errors=[],failedRequests=[],checks=[];
page.on('pageerror',e=>errors.push(e.message));
page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
page.on('requestfailed',r=>failedRequests.push(r.url()));
page.on('response',r=>{if(r.status()>=400)failedRequests.push(`${r.status()} ${r.url()}`);});
await mkdir(path.join(root,'review_codex'),{recursive:true});
const shot=async name=>{await page.evaluate(()=>document.fonts.ready);await page.screenshot({path:path.join(root,`review_codex/${name}_codex.png`),fullPage:true,animations:'disabled',style:'#toast{visibility:hidden}'});};
const action=name=>page.locator(`[data-action="${name}"]`);
const nav=name=>page.locator(`.topbar [data-page="${name}"]`);
const setting=name=>page.locator(`.sidebar [data-page="${name}"]`);
const check=(name)=>{checks.push(name);console.log('PASS',name);};
try{
 await page.goto('http://127.0.0.1:8765/');
 await page.evaluate(()=>document.fonts.ready);
 assert.equal(await page.locator('h1').innerText(),'Your voice, in writing.');
 assert.equal(await page.evaluate(()=>document.fonts.check('14px Geist')),true);
 await shot('workspace_light');check('Workspace and bundled Geist font load');
 await action('theme').click();assert.equal(await page.locator('html').getAttribute('data-theme'),'dark');
 await shot('workspace_dark');await page.reload();assert.equal(await page.locator('html').getAttribute('data-theme'),'dark');
 check('Dark mode renders and persists across reload');
 await action('theme').click();
 await action('record').click();assert.match(await page.locator('#record-status').innerText(),/Listening/);
 await shot('recording');await action('record').click();assert.equal(await action('record').isDisabled(),true);
 await shot('processing');await page.waitForFunction(()=>document.querySelector('#record-status')?.textContent.includes('Ready'));
 assert.match(await page.locator('#toast').innerText(),/ready to review/);check('Recording → processing → completed transcript');
 await page.locator('[data-tab="raw"]').click();assert.match(await page.locator('.transcript-body').innerText(),/um/);
 await page.locator('[data-tab="clean"]').click();assert.ok(!(await page.locator('.transcript-body').innerText()).includes('um,'));
 await action('copy-current').click();assert.match(await page.evaluate(()=>navigator.clipboard.readText()),/next design review/);check('Original/polished versions and clipboard');
 await page.keyboard.press('Control+Shift+Space');assert.match(await page.locator('#record-status').innerText(),/Listening/);
 await page.keyboard.press('Escape');assert.match(await page.locator('#record-status').innerText(),/Ready/);check('Start shortcut and Escape cancellation');
 await nav('settings').click();assert.equal(await page.locator('h1').innerText(),'Recording');await shot('settings_light');
 await page.locator('#mic').selectOption('USB microphone');
 await action('test-mic').click();assert.equal(await page.locator('.meter.running').count(),1);await action('test-mic').click();
 await page.locator('[data-mode="hold"]').click();await nav('workspace').click();
 await page.keyboard.down('Control');await page.keyboard.down('Shift');await page.keyboard.down('Space');assert.match(await page.locator('#record-status').innerText(),/Listening/);
 await page.keyboard.up('Space');await page.keyboard.up('Shift');await page.keyboard.up('Control');
 assert.equal(await action('record').isDisabled(),true);await page.waitForFunction(()=>document.querySelector('#record-status')?.textContent.includes('Ready'));
 check('Microphone selection, preview, and hold-to-talk');
 await nav('settings').click();await setting('models').click();await page.locator('[data-key="stt"]').click();assert.equal(await page.locator('[data-key="stt"]').isDisabled(),true);await page.waitForFunction(()=>document.body.textContent.includes('Test passed · demo'));
 await setting('cleanup').click();await page.locator('#instructions').fill('Keep my technical vocabulary.');await action('save-instructions').click();await page.getByRole('switch',{name:'Polish after dictation'}).click();assert.equal(await page.locator('#instructions').isDisabled(),true);await page.getByRole('switch',{name:'Polish after dictation'}).click();check('Model loading feedback and cleanup settings');
 await setting('appearance').click();await page.locator('.theme-choice[data-theme="dark"]').click();await shot('settings_dark');await page.getByRole('switch',{name:'Reduce motion'}).click();assert.equal(await page.locator('html').getAttribute('data-motion'),'reduced');
 await page.locator('.theme-choice[data-theme="light"]').click();check('Appearance themes and reduced motion');
 await nav('dictionary').click();await action('add-word').click();await page.locator('#word').fill('Kubernetes');await page.locator('#sounds').fill('koo ber net ees');await page.getByRole('button',{name:'Add word',exact:true}).click();assert.match(await page.locator('.dictionary-table').innerText(),/Kubernetes/);
 await action('add-word').click();await page.locator('#word').fill('Kubernetes');await page.getByRole('button',{name:'Add word',exact:true}).click();assert.match(await page.locator('#word-error').innerText(),/already/);await page.keyboard.press('Escape');
 await page.getByRole('button',{name:'Edit Kubernetes',exact:true}).click();await page.locator('#word').fill('K8s');await page.getByRole('button',{name:'Save changes',exact:true}).click();
 await page.locator('#dictionary-search').fill('K8s');assert.equal(await page.locator('.dictionary-table tbody tr').count(),1);await page.locator('#dictionary-search').fill('');await shot('dictionary');
 const downloadPromise=page.waitForEvent('download');await action('export-words').click();assert.equal((await downloadPromise).suggestedFilename(),'dictionary_codex.json');
 await page.locator('#dictionary-import').setInputFiles({name:'import_codex.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify([{word:'TypeScript',sounds:'type script'}]))});await page.waitForFunction(()=>document.body.textContent.includes('TypeScript'));
 await page.locator('#dictionary-import').setInputFiles({name:'invalid_codex.json',mimeType:'application/json',buffer:Buffer.from('{invalid')});await page.locator('dialog[open]').waitFor();assert.match(await page.locator('#dialog-title').innerText(),/Couldn’t/);await page.keyboard.press('Escape');
 await page.getByRole('button',{name:'Delete K8s',exact:true}).click();await action('confirm-delete-word').click();assert.ok(!(await page.locator('.dictionary-table').innerText()).includes('K8s'));check('Dictionary add/edit/search/delete, duplicate validation, import/export, malformed import');
 await nav('history').click();await page.locator('#history-search').fill('team');assert.equal(await page.locator('.history-row').count(),1);await action('open-history').click();await page.locator('dialog summary').click();assert.match(await page.locator('dialog').innerText(),/uh/);await page.keyboard.press('Escape');
 await page.locator('#history-search').fill('unfindable987');assert.match(await page.locator('#history-results').innerText(),/No matching/);await page.locator('#history-search').fill('');check('History search, transcript details, and no results');
 await nav('workspace').click();await action('states').click();await page.locator('[data-state="warning"]').click();await shot('warning');assert.equal(await page.locator('.notice.warning').count(),1);
 await action('states').click();await page.locator('[data-state="error"]').click();await shot('error');await action('recover').click();assert.match(await page.locator('#record-status').innerText(),/Ready/);
 await action('states').click();await page.locator('[data-state="empty"]').click();assert.match(await page.locator('.empty').first().innerText(),/blank page/);check('Warning, error, recovery, and empty state previews');
 await action('shortcuts').click();for(let i=0;i<7;i++)await page.keyboard.press('Tab');assert.equal(await page.evaluate(()=>document.querySelector('dialog').contains(document.activeElement)),true);await page.keyboard.press('Escape');assert.equal(await page.evaluate(()=>document.activeElement.dataset.action),'shortcuts');check('Modal focus trap and focus restoration');
 await nav('settings').click();await setting('privacy').click();await action('clear-history').click();await action('confirm-clear').click();await nav('history').click();assert.match(await page.locator('.empty').innerText(),/fresh start/);
 await nav('settings').click();await setting('privacy').click();await page.getByRole('switch',{name:'Save dictation history'}).click();await nav('workspace').click();await action('record').click();await action('record').click();await page.waitForFunction(()=>document.querySelector('#record-status')?.textContent.includes('Ready'));await nav('history').click();assert.equal(await page.locator('.history-row').count(),0);check('Clear history and disabled retention');
 await nav('settings').click();await setting('privacy').click();await action('restore').click();await action('confirm-restore').click();await nav('history').click();assert.equal(await page.locator('.history-row').count(),3);check('Restore sample data');
 const contrast=await page.evaluate(()=>{
  function rgb(c){return c.match(/[\d.]+/g).slice(0,3).map(Number);}
  function lum(c){return rgb(c).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);}
  function ratio(fg,bg){const a=lum(fg),b=lum(bg);return +((Math.max(a,b)+.05)/(Math.min(a,b)+.05)).toFixed(2);}
  const results={};const root=document.documentElement;const old=root.dataset.theme;
  for(const theme of ['light','dark']){root.dataset.theme=theme;const cs=getComputedStyle(root);const pairs=[['text','bg'],['muted','bg'],['primary-text','primary-soft'],['on-primary','primary'],['green','green-soft'],['blue','blue-soft'],['yellow','yellow-soft'],['red','red-soft']];
   for(const [fg,bg]of pairs){const probe=document.createElement('span');probe.style.color=cs.getPropertyValue('--'+fg);probe.style.backgroundColor=cs.getPropertyValue('--'+bg);document.body.append(probe);const s=getComputedStyle(probe);results[`${theme}:${fg}/${bg}`]=ratio(s.color,s.backgroundColor);probe.remove();}}
  root.dataset.theme=old;return results;
 });
 for(const [pair,value]of Object.entries(contrast))assert.ok(value>=4.5,`${pair} contrast ${value}`);check('Core text/accent/semantic color pairs meet 4.5:1 contrast');
 for(const size of [{width:1024,height:768},{width:1280,height:800},{width:1920,height:1080}]){
  await page.setViewportSize(size);for(const target of ['workspace','settings','dictionary','history']){await nav(target).click();assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${target} overflow at ${size.width}`);if(target==='settings'){for(const [key]of [['recording'],['models'],['cleanup'],['appearance'],['privacy']]){await setting(key).click();assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${key} overflow at ${size.width}`);}}}
  if(size.width===1024){await nav('workspace').click();await shot('compact_desktop');}
 }check('No horizontal overflow at 1024, 1280, and 1920 desktop widths across every page');
 await page.emulateMedia({reducedMotion:'reduce'});await nav('workspace').click();await action('record').click();assert.equal(await page.locator('.waveform span').first().evaluate(e=>getComputedStyle(e).animationName),'none');await page.keyboard.press('Escape');check('OS reduced motion honored');
 const direct=await context.newPage();await direct.goto('file://'+path.join(root,'index_codex.html'));assert.equal(await direct.locator('h1').innerText(),'Your voice, in writing.');await direct.close();check('Direct HTML file preview works');
 assert.deepEqual(errors,[]);assert.deepEqual(failedRequests,[]);check('No page/console errors or failed HTTP assets');
 const report={date:new Date().toISOString(),browser:await browser.version(),checks,contrast,errors,failedRequests,scope:'Chromium functional checks and selected visual screenshots; not a complete accessibility audit. Recording/models are simulations.'};
 await writeFile(path.join(root,'review_codex/results_codex.json'),JSON.stringify(report,null,2));console.log(`\n${checks.length} check groups passed.`);
}finally{await browser.close();}
