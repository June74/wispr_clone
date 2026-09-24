import assert from 'node:assert/strict';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {writeFile} from 'node:fs/promises';
const root=path.dirname(fileURLToPath(import.meta.url));
process.env.PLAYWRIGHT_BROWSERS_PATH=path.join(root,'.tools_codex/browsers');
const {chromium}=await import('./.tools_codex/node_modules/playwright/index.mjs');
const browser=await chromium.launch({headless:true,env:{...process.env,LD_LIBRARY_PATH:path.join(root,'.tools_codex/libs/usr/lib/x86_64-linux-gnu')}});
const context=await browser.newContext({viewport:{width:1280,height:900},permissions:['clipboard-read','clipboard-write']});
const page=await context.newPage();
const errors=[],checks=[];
page.on('pageerror',e=>errors.push(e.message));
const action=name=>page.locator(`[data-action="${name}"]`);
const check=name=>{checks.push(name);console.log('PASS',name);};
async function screenshot(name){
  const box=await page.locator('.dictation-hud').boundingBox();
  await page.screenshot({path:path.join(root,`review_codex/hud_${name}_codex.png`),clip:{x:box.x-30,y:box.y-25,width:box.width+60,height:box.height+50},animations:'disabled',style:'#toast{visibility:hidden}'});
}
try{
 await page.goto('http://127.0.0.1:8765/');await page.evaluate(()=>document.fonts.ready);
 assert.equal(await page.locator('.dictation-hud').count(),0);
 await action('preview-hud').click();assert.match(await page.locator('.hud-message').innerText(),/Listening/);
 await page.waitForFunction(()=>document.querySelector('#hud-timer')?.textContent==='00:01');
 assert.equal(await page.locator('#timer').innerText(),await page.locator('#hud-timer').innerText());
 await screenshot('light');
 await page.screenshot({path:path.join(root,'review_codex/hud_workspace_codex.png'),animations:'disabled'});
 await action('theme').click();await screenshot('dark');check('HUD opens with recording, shares timer, and follows light/dark theme');
 await page.locator('.topbar [data-page="settings"]').click();assert.equal(await page.locator('.dictation-hud.recording').count(),1);
 await action('hud-finish').click();assert.equal(await page.locator('.dictation-hud.processing').count(),1);assert.equal(await action('hud-finish').isDisabled(),true);
 await screenshot('processing');await page.waitForSelector('.dictation-hud.complete');await screenshot('complete');
 await action('hud-copy').click();assert.match(await page.evaluate(()=>navigator.clipboard.readText()),/design review/);await action('hud-dismiss').click();assert.equal(await page.locator('.dictation-hud').count(),0);check('HUD survives page navigation; finish, processing, copy, and dismiss work');
 await action('preview-hud').click();await action('hud-cancel').click();assert.equal(await page.locator('.dictation-hud').count(),0);
 await action('preview-hud').click();await action('hud-finish').click();await action('hud-cancel').click();await page.waitForTimeout(1800);assert.equal(await page.locator('.dictation-hud').count(),0);check('Cancel stops recording and pending processing without stale completion');
 await page.keyboard.press('Control+Shift+Space');assert.equal(await page.locator('.dictation-hud.recording').count(),1);await page.keyboard.press('Escape');assert.equal(await page.locator('.dictation-hud').count(),0);check('Keyboard recording and Escape control the HUD');
 for(const state of ['warning','error']){await action('states').click();await page.locator(`[data-state="${state}"]`).click();assert.equal(await page.locator(`.dictation-hud.${state}`).count(),1);await screenshot(state);await action('hud-recover').click();assert.equal(await page.locator('.dictation-hud').count(),0);}check('Warning/error previews and recovery work');
 await page.emulateMedia({reducedMotion:'reduce'});await action('preview-hud').click();assert.equal(await page.locator('.hud-wave i').first().evaluate(el=>getComputedStyle(el).animationName),'none');
 await page.setViewportSize({width:1024,height:768});const box=await page.locator('.dictation-hud').boundingBox();assert.ok(box.x>=0&&box.x+box.width<=1024&&box.y+box.height<729);await action('hud-cancel').click();check('Reduced motion and compact desktop positioning');
 await action('preview-hud').click();await action('hud-finish').click();await page.waitForSelector('.dictation-hud.complete');await action('hud-copy').focus();await page.waitForSelector('.dictation-hud',{state:'detached',timeout:6500});assert.equal(await page.evaluate(()=>document.activeElement.classList.contains('record-btn')),true);check('Completion auto-hides after five seconds and restores keyboard focus');
 assert.deepEqual(errors,[]);check('No browser JavaScript errors');
 await writeFile(path.join(root,'review_codex/hud_results_codex.json'),JSON.stringify({date:new Date().toISOString(),checks,errors},null,2));
}finally{await browser.close();}
