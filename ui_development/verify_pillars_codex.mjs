import assert from 'node:assert/strict';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {writeFile} from 'node:fs/promises';
const root=path.dirname(fileURLToPath(import.meta.url));
process.env.PLAYWRIGHT_BROWSERS_PATH=path.join(root,'.tools_codex/browsers');
const {chromium}=await import('./.tools_codex/node_modules/playwright/index.mjs');
const rate=48000,duration=8,count=rate*duration,pcm=Buffer.alloc(44+count*2);
pcm.write('RIFF',0);pcm.writeUInt32LE(36+count*2,4);pcm.write('WAVEfmt ',8);pcm.writeUInt32LE(16,16);pcm.writeUInt16LE(1,20);pcm.writeUInt16LE(1,22);pcm.writeUInt32LE(rate,24);pcm.writeUInt32LE(rate*2,28);pcm.writeUInt16LE(2,32);pcm.writeUInt16LE(16,34);pcm.write('data',36);pcm.writeUInt32LE(count*2,40);
for(let i=0;i<count;i++){const t=i/rate;const active=t>1&&t<4;const value=active?(.16+.05*Math.sin(t*13))*(Math.sin(t*2*Math.PI*220)+.4*Math.sin(t*2*Math.PI*780)+.2*Math.sin(t*2*Math.PI*1600)):0;pcm.writeInt16LE(Math.round(value*32767),44+i*2);}
const fixture=path.join(root,'.tools_codex/pillars_input_codex.wav');await writeFile(fixture,pcm);
const browser=await chromium.launch({headless:true,args:['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream',`--use-file-for-fake-audio-capture=${fixture}`],env:{...process.env,LD_LIBRARY_PATH:path.join(root,'.tools_codex/libs/usr/lib/x86_64-linux-gnu')}});
const context=await browser.newContext({viewport:{width:1440,height:1200},permissions:['microphone']});
const page=await context.newPage();const checks=[],errors=[];
page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});page.on('response',r=>{if(r.status()>=400)errors.push(`${r.status()} ${r.url()}`);});
const check=name=>{checks.push(name);console.log('PASS',name);};
const pixels=()=>page.evaluate(()=>[...document.querySelectorAll('canvas')].map(c=>c.toDataURL()));
try{
 await page.goto('http://127.0.0.1:8767/waveforms_codex.html');await page.evaluate(()=>waveformReview.frameAt(0));const original=await page.locator('canvas[data-design="pillars"][data-live="false"]').evaluate(c=>c.toDataURL());
 await page.goto('http://127.0.0.1:8767/pillars_codex.html');await page.evaluate(()=>document.fonts.ready);await page.evaluate(()=>waveformReview.frameAt(0));
 assert.equal(await page.locator('.design-study').count(),5);const defaults=await pixels();assert.equal(defaults.length,10);assert.ok(defaults.every(p=>p===original));check('All five default and silent states exactly match original Quiet Pillars pixels');
 const result=await page.evaluate(()=>{
   const ids=waveformReview.designs.map(d=>d.id);
   const wave=Float32Array.from({length:128},(_,i)=>Math.sin(i*.19)*.8);
   const low=Float32Array.from({length:32},(_,i)=>Math.exp(-((i-6)**2)/5));
   const high=Float32Array.from({length:32},(_,i)=>Math.exp(-((i-24)**2)/5));
   return ids.map(id=>{
     const quiet=pillarsReview.geometry(id,{level:.2,bands:low,wave});const loud=pillarsReview.geometry(id,{level:.8,bands:low,wave});const pitched=pillarsReview.geometry(id,{level:.8,bands:high,wave});
     return {id,grows:loud.every((p,i)=>p.height>quiet[i].height),frequencyChanges:loud.some((p,i)=>Math.abs(p.height-pitched[i].height)>.3),individual:loud.some((p,i)=>i>0&&Math.abs(p.height-loud[i-1].height)>.3),bounds:loud.every(p=>p.center-p.height/2>=0&&p.center+p.height/2<=72),xStable:loud.every((p,i)=>p.x===44+i*9&&p.width===3),profile:loud.map(p=>[p.height,p.center])};
   });
 });
 for(const r of result){assert.ok(r.grows,`${r.id} loudness growth`);assert.ok(r.frequencyChanges,`${r.id} frequency response`);assert.ok(r.individual,`${r.id} independent pillar heights`);assert.ok(r.bounds&&r.xStable,`${r.id} fixed column geometry`);}
 assert.equal(new Set(result.map(r=>JSON.stringify(r.profile))).size,5);check('Each animation grows with loudness, differentiates frequency bands, and keeps pillar spacing/width');
 await page.evaluate(()=>waveformReview.frameAt(2.8));const active=await pixels();for(let i=0;i<10;i+=2){assert.equal(active[i],original);assert.ok(active[i+1]!==original);}check('Active states are distinct from rest while default previews stay unchanged');
 await page.locator('#thread-envelope').screenshot({path:path.join(root,'review_codex/pillars_component_codex.png'),animations:'disabled'});
 await page.locator('#overview').click();await page.evaluate(()=>waveformReview.frameAt(2.8));await page.screenshot({path:path.join(root,'review_codex/pillars_light_codex.png'),fullPage:true,animations:'disabled'});
 await page.locator('#theme-toggle').click();await page.evaluate(()=>waveformReview.frameAt(2.8));await page.screenshot({path:path.join(root,'review_codex/pillars_dark_codex.png'),fullPage:true,animations:'disabled'});check('Component and light/dark comparison sheets captured');
 if(process.argv.includes('--captures-only')){await browser.close();process.exit(0);}
 await page.locator('#sample-pattern').selectOption('volume');await page.evaluate(()=>waveformReview.frameAt(1.2));const small=await pixels();await page.evaluate(()=>waveformReview.frameAt(10.2));const big=await pixels();for(let i=1;i<10;i+=2)assert.ok(small[i]!==big[i]);
 await page.locator('#sample-pattern').selectOption('pitch');await page.evaluate(()=>waveformReview.frameAt(1.5));const bass=await pixels();await page.evaluate(()=>waveformReview.frameAt(8.5));const treble=await pixels();for(let i=1;i<10;i+=2)assert.ok(bass[i]!==treble[i]);
 await page.locator('#sample-pattern').selectOption('silence');await page.waitForTimeout(150);const silent=await pixels();for(let i=0;i<10;i+=2)assert.equal(silent[i],silent[i+1]);check('Quiet/loud, low/high-frequency, and silence sample modes work');
 await page.locator('#sample-pattern').selectOption('phrasing');await page.waitForFunction(()=>waveformReview.level>.3);const moving=await pixels();await page.waitForTimeout(130);const moved=await pixels();assert.ok(moving.some((p,i)=>i%2&&p!==moved[i]));await page.keyboard.press('Escape');assert.equal(await page.evaluate(()=>waveformReview.mode),'idle');check('Animations fluctuate over time and Escape returns to rest');
 await page.locator('#use-mic').click();await page.waitForFunction(()=>waveformReview.mode==='mic');await page.waitForFunction(()=>waveformReview.level>.08,{},{timeout:7000});await page.waitForTimeout(100);const micActive=await pixels();await page.waitForFunction(()=>waveformReview.level===0,{},{timeout:7000});await page.waitForTimeout(100);const micQuiet=await pixels();
 for(let i=0;i<10;i+=2){assert.ok(micActive[i+1]!==micQuiet[i+1]);assert.equal(micQuiet[i],micQuiet[i+1]);}await page.locator('#stop-input').click();assert.deepEqual(await page.evaluate(()=>waveformReview.tracks),[]);check('All five react through the microphone analyser using synthetic capture and settle in silence');
 await page.emulateMedia({reducedMotion:'reduce'});await page.waitForFunction(()=>document.querySelector('#motion-note').textContent.includes('Reduced motion'));await page.setViewportSize({width:1024,height:768});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));check('Reduced motion and compact desktop layout');
 const videoContext=await browser.newContext({viewport:{width:1440,height:1200},recordVideo:{dir:path.join(root,'.tools_codex/pillars_video'),size:{width:1440,height:1200}}});const vp=await videoContext.newPage();await vp.goto('http://127.0.0.1:8767/pillars_codex.html');await vp.locator('#overview').click();await vp.locator('#play-sample').click();await vp.waitForTimeout(12300);await vp.locator('#sample-pattern').selectOption('volume');await vp.waitForTimeout(12000);await vp.locator('#sample-pattern').selectOption('pitch');await vp.waitForTimeout(12000);const video=vp.video();await videoContext.close();await video.saveAs(path.join(root,'review_codex/pillars_animation_codex.webm'));check('Exported animation video with phrasing, loudness ramp, and frequency sweep');
 assert.deepEqual(errors,[]);check('No JavaScript errors or failed assets');await writeFile(path.join(root,'review_codex/pillars_results_codex.json'),JSON.stringify({date:new Date().toISOString(),checks,errors,geometry:result,limits:'Microphone path checked with synthetic Chromium capture. No physical microphone or musical note detection tested.'},null,2));
}finally{await browser.close();}
