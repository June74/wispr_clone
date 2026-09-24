import assert from 'node:assert/strict';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {mkdir,writeFile} from 'node:fs/promises';
const root=path.dirname(fileURLToPath(import.meta.url));
process.env.PLAYWRIGHT_BROWSERS_PATH=path.join(root,'.tools_codex/browsers');
const {chromium}=await import('./.tools_codex/node_modules/playwright/index.mjs');
await mkdir(path.join(root,'review_codex'),{recursive:true});
// Synthetic microphone fixture: a quiet interval, speech-band tones, then quiet.
// No person is recorded; this tests the actual getUserMedia/AnalyserNode path.
const rate=48000,duration=8,count=rate*duration,pcm=Buffer.alloc(44+count*2);
pcm.write('RIFF',0);pcm.writeUInt32LE(36+count*2,4);pcm.write('WAVEfmt ',8);pcm.writeUInt32LE(16,16);pcm.writeUInt16LE(1,20);pcm.writeUInt16LE(1,22);pcm.writeUInt32LE(rate,24);pcm.writeUInt32LE(rate*2,28);pcm.writeUInt16LE(2,32);pcm.writeUInt16LE(16,34);pcm.write('data',36);pcm.writeUInt32LE(count*2,40);
for(let i=0;i<count;i++){const t=i/rate;const active=t>1&&t<4;const value=active?(.16+.05*Math.sin(t*13))*(Math.sin(t*2*Math.PI*220)+.4*Math.sin(t*2*Math.PI*780)+.2*Math.sin(t*2*Math.PI*1600)):0;pcm.writeInt16LE(Math.round(value*32767),44+i*2);}
const fixture=path.join(root,'.tools_codex/waveform_input_codex.wav');await writeFile(fixture,pcm);
const browser=await chromium.launch({headless:true,args:['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream',`--use-file-for-fake-audio-capture=${fixture}`],env:{...process.env,LD_LIBRARY_PATH:path.join(root,'.tools_codex/libs/usr/lib/x86_64-linux-gnu')}});
const context=await browser.newContext({viewport:{width:1440,height:1200},permissions:['microphone']});
const page=await context.newPage();const errors=[],checks=[];
page.on('pageerror',error=>errors.push(error.message));
page.on('console',msg=>{if(msg.type()==='error')errors.push(msg.text());});
page.on('response',r=>{if(r.status()>=400)errors.push(`${r.status()} ${r.url()}`);});
const check=name=>{checks.push(name);console.log('PASS',name);};
const snapshots=()=>page.evaluate(()=>[...document.querySelectorAll('canvas')].map(c=>({id:c.dataset.design,live:c.dataset.live,pixels:c.toDataURL()})));
try{
 await page.goto('http://127.0.0.1:8766/');await page.evaluate(()=>document.fonts.ready);
 assert.equal(await page.locator('.design-study').count(),10);assert.equal(await page.locator('canvas').count(),20);
 await page.evaluate(()=>waveformReview.frameAt(0));let quiet=await snapshots();
 for(let i=0;i<20;i+=2)assert.equal(quiet[i].pixels,quiet[i+1].pixels,`${quiet[i].id}: silence must equal its default`);
 assert.equal(new Set(quiet.filter(x=>x.live==='false').map(x=>x.pixels)).size,10);check('Ten distinct defaults, each matching zero-input animation state');
 await page.evaluate(()=>waveformReview.frameAt(1.45));const first=await snapshots();await page.evaluate(()=>waveformReview.frameAt(5.8));const second=await snapshots();
 for(let i=0;i<20;i+=2){assert.equal(first[i].pixels,second[i].pixels);assert.notEqual(first[i+1].pixels,second[i+1].pixels,`${first[i].id} responds to different input`);assert.notEqual(first[i+1].pixels,quiet[i+1].pixels);}
 check('Every design reacts to input; all default previews remain still');
 const geometry=await page.evaluate(()=>[...document.querySelectorAll('.design-study')].map(row=>{const cards=[...row.querySelectorAll('.record-card')];return cards.map(card=>{const parent=card.getBoundingClientRect();return ['.record-top','.waveform','.record-caption','.record-btn','.record-hint'].map(s=>{const r=card.querySelector(s).getBoundingClientRect();return {y:r.y-parent.y,height:r.height,width:r.width};});});}));
 for(const [left,right]of geometry)assert.deepEqual(left,right);check('Default and animated cards keep identical component geometry');
 await page.evaluate(()=>waveformReview.frameAt(1.45));await page.locator('#pillars').screenshot({path:path.join(root,'review_codex/waveforms_component_codex.png'),animations:'disabled'});
 await page.locator('#overview').click();await page.evaluate(()=>waveformReview.frameAt(1.45));await page.screenshot({path:path.join(root,'review_codex/waveforms_overview_light_codex.png'),fullPage:true,animations:'disabled'});
 await page.locator('#theme-toggle').click();await page.evaluate(()=>waveformReview.frameAt(1.45));await page.screenshot({path:path.join(root,'review_codex/waveforms_overview_dark_codex.png'),fullPage:true,animations:'disabled'});
 check('Light/dark comparison sheets and full component captured');
 if(process.argv.includes('--captures-only')){await browser.close();process.exit(0);}
 await page.locator('#play-sample').click();await page.waitForFunction(()=>waveformReview.level>.1);const animated=await snapshots();await page.waitForTimeout(180);const next=await snapshots();assert.notEqual(animated[1].pixels,next[1].pixels);assert.equal(animated[0].pixels,next[0].pixels);
 await page.locator('#stop-input').click();assert.equal(await page.evaluate(()=>waveformReview.level),0);check('Timed sample animates only talking previews and stops cleanly');
 await page.locator('#use-mic').click();await page.waitForFunction(()=>waveformReview.mode==='mic');assert.deepEqual(await page.evaluate(()=>waveformReview.tracks),['live']);
 await page.waitForFunction(()=>waveformReview.level>.08,{},{timeout:7000});await page.waitForTimeout(80);const speech=await snapshots();
 await page.waitForFunction(()=>waveformReview.level===0,{},{timeout:7000});await page.waitForTimeout(100);const silence=await snapshots();
 for(let i=0;i<20;i+=2){assert.ok(speech[i+1].pixels!==silence[i+1].pixels,`${speech[i].id}: microphone speech vs silence`);assert.ok(silence[i].pixels===silence[i+1].pixels,`${silence[i].id}: settled silence`);}
 await page.keyboard.press('Escape');assert.deepEqual(await page.evaluate(()=>waveformReview.tracks),[]);assert.equal(await page.evaluate(()=>waveformReview.mode),'idle');check('Real microphone-analysis code reacts to a synthetic capture fixture and settles in silence; Escape releases input');
 await page.emulateMedia({reducedMotion:'reduce'});await page.waitForFunction(()=>document.querySelector('#motion-note').textContent.includes('Reduced motion'));assert.match(await page.locator('#motion-note').innerText(),/Reduced motion/);await page.locator('#play-sample').click();await page.locator('#stop-input').click();check('Reduced-motion mode and explicit sample control');
 await page.setViewportSize({width:1024,height:768});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.locator('#overview').click();assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));check('Overview and component layout fit 1024 px desktop');
 const denied=await context.newPage();await denied.addInitScript(()=>{navigator.mediaDevices.getUserMedia=async()=>{throw new DOMException('Denied','NotAllowedError');};});await denied.goto('http://127.0.0.1:8766/');await denied.locator('#use-mic').click();await denied.waitForFunction(()=>!document.querySelector('#input-error').hidden);assert.match(await denied.locator('#input-error').innerText(),/declined/);await denied.locator('#play-sample').click();assert.equal(await denied.locator('#input-error').isHidden(),true);await denied.close();check('Denied microphone permission offers a working sample fallback');
 const late=await context.newPage();await late.addInitScript(()=>{const original=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);navigator.mediaDevices.getUserMedia=async options=>{const stream=await original(options);window.pendingTestTracks=stream.getTracks();await new Promise(resolve=>setTimeout(resolve,900));return stream;};});await late.goto('http://127.0.0.1:8766/');await late.locator('#use-mic').click();await late.waitForFunction(()=>window.pendingTestTracks?.length);await late.locator('#stop-input').click();await late.waitForFunction(()=>window.pendingTestTracks.every(t=>t.readyState==='ended'));assert.equal(await late.evaluate(()=>waveformReview.mode),'idle');await late.close();check('Canceling a pending microphone request releases the eventual stream');
 // A standalone silent animation video of all ten variants, with a full sample cycle.
 const videoContext=await browser.newContext({viewport:{width:1440,height:1200},recordVideo:{dir:path.join(root,'.tools_codex/waveform_video'),size:{width:1440,height:1200}}});
 const videoPage=await videoContext.newPage();await videoPage.goto('http://127.0.0.1:8766/');await videoPage.locator('#overview').click();await videoPage.locator('#play-sample').click();await videoPage.waitForTimeout(12300);const video=videoPage.video();await videoContext.close();await video.saveAs(path.join(root,'review_codex/waveforms_animation_codex.webm'));check('Exported a silent overview video with speech-shaped motion and pauses');
 assert.deepEqual(errors,[]);check('No page/console errors or failed assets');
 await writeFile(path.join(root,'review_codex/waveforms_results_codex.json'),JSON.stringify({date:new Date().toISOString(),checks,errors,limits:'Live path tested using Chromium synthetic microphone capture, not a physical microphone or speech detector.'},null,2));
}finally{await browser.close();}
