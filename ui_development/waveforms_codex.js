'use strict';

// Isolated comparison study. The approved app and HUD are left intact.
// A single input frame drives every alternative so comparisons are fair.
const variantSet = window.waveformVariantSet;
const designs = variantSet?.designs || [
  {id:'pillars',name:'Quiet pillars',note:'A dotted resting line opens into slender, rounded bars.',motion:'Height follows voice energy; individual bars follow frequency bands.'},
  {id:'ribbon',name:'Soft ribbon',note:'A fine spindle unfolds into one continuous silhouette.',motion:'A filled, symmetric envelope expands on syllables and closes in pauses.'},
  {id:'thread',name:'Fine thread',note:'A delicate center notch becomes a drawn audio trace.',motion:'The microphone’s time-domain samples directly shape the line.'},
  {id:'twin',name:'Twin contours',note:'Two quiet lines frame a little space for your voice.',motion:'Mirrored contours separate with volume and contour with spectral energy.'},
  {id:'dots',name:'Dot field',note:'A low-key dot grid lights outward as you speak.',motion:'Frequency bands activate dots above and below the center row.'},
  {id:'segments',name:'Segmented meter',note:'Short ticks build into tidy stacks of small segments.',motion:'Each stack grows with a band of the voice; quiet input clears the stacks.'},
  {id:'capsules',name:'Five capsules',note:'Five compact pills make the smallest visual footprint.',motion:'Broad frequency groups drive five deliberately rounded columns.'},
  {id:'bloom',name:'Voice bloom',note:'A still circular mark opens into a radial waveform.',motion:'Radial lengths respond to the spectrum. No rotation or idle breathing.'},
  {id:'rings',name:'Resonance rings',note:'Three nested rings widen with the weight of your voice.',motion:'Low, middle, and high frequency energy reshape three concentric ellipses.'},
  {id:'trail',name:'Phrase trail',note:'A quiet dotted line gathers the rhythm of a phrase.',motion:'Recent energy accumulates from left to right, then settles during silence.'},
];
const lineIcons={wave:'M3 10v4m4-8v12m5-15v18m5-16v14m4-10v6',mic:'M12 15a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v7a3 3 0 0 0 3 3ZM5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8'};
const icon=name=>`<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${lineIcons[name]}"/></svg>`;
const clamp=(v,min=0,max=1)=>Math.max(min,Math.min(max,v));
const emptyFrame=()=>({level:0,bands:new Float32Array(32),wave:new Float32Array(128),history:Array(40).fill(0)});
const reducedMotion=matchMedia('(prefers-reduced-motion: reduce)');
let mode='idle',stream=null,audioContext=null,source=null,analyser=null;
let requestGeneration=0,sampleStart=0,lastTick=0,lastPaint=0,lastHistory=0,level=0;
let bands=new Float32Array(32),history=Array(40).fill(0),lastFrame=emptyFrame();
let frequencyData,timeData,micFloor=.012;
let color='',views=[],rafId=0;
const statuses={sample:'Sample preview · synthetic speech-shaped input',mic:'Microphone live · analyzed locally, not recorded',idle:'Input stopped · all waveforms at rest',requesting:'Waiting for microphone permission…'};

function component(id,live){
  // Same classes, DOM ordering, text, button, and spacing as recorder() in app_codex.js.
  return `<section class="card record-card" aria-label="${id} ${live?'reactive':'default'} component"><div class="record-top"><span class="state-label small">${icon('wave')}Ready when you are</span><span class="eyebrow">TRY IT OUT</span></div>
    <div class="waveform waveform-slot"><canvas width="680" height="144" data-design="${id}" data-live="${live}" aria-label="${id}: ${live?'audio-reactive waveform':'still default waveform'}"></canvas></div>
    <div class="record-caption">From a passing thought to the perfect words.</div>
    <button type="button" class="btn primary record-btn" data-mic>${icon('mic')}Start dictation</button>
    <div class="record-hint">or press <kbd>Ctrl + Shift + Space</kbd></div></section>`;
}
document.querySelector('#comparisons').innerHTML=designs.map((d,i)=>`<article class="design-study" id="${d.id}"><div class="study-heading"><span class="study-number">${String(i+1).padStart(2,'0')}</span><h2>${d.name}</h2><p>${d.note}</p></div><div class="comparison-pair"><div><div class="preview-label">Default · still</div>${component(d.id,false)}</div><div><div class="preview-label">Talking · <span class="source-label">sample input</span></div>${component(d.id,true)}</div></div><p class="live-note">${d.motion}</p></article>`).join('');
document.querySelector('#design-index').innerHTML=designs.map((d,i)=>`<a href="#${d.id}">${String(i+1).padStart(2,'0')} ${d.name}</a>`).join('');
views=[...document.querySelectorAll('canvas')].map(canvas=>({canvas,ctx:canvas.getContext('2d'),id:canvas.dataset.design,live:canvas.dataset.live==='true',visible:true}));
const observer=new IntersectionObserver(entries=>{for(const entry of entries){const view=views.find(v=>v.canvas===entry.target);view.visible=entry.isIntersecting;if(view.visible)draw(view,view.live?lastFrame:emptyFrame());}},{rootMargin:'100px'});
views.forEach(v=>observer.observe(v.canvas));

// Drawing coordinates are always 340 × 72; high-DPI backing stores stay sharp.
function stroke(ctx,points,width=2,opacity=1){ctx.globalAlpha=opacity;ctx.lineWidth=width;ctx.beginPath();points.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.stroke();}
function bar(ctx,x,height,width,opacity=.85){ctx.globalAlpha=opacity;ctx.lineWidth=width;ctx.beginPath();ctx.moveTo(x,36-height/2);ctx.lineTo(x,36+height/2);ctx.stroke();}
function dot(ctx,x,y,r,opacity){ctx.globalAlpha=opacity;ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fill();}
function smoothPath(ctx,points){ctx.moveTo(...points[0]);for(let i=1;i<points.length-1;i++){const end=[(points[i][0]+points[i+1][0])/2,(points[i][1]+points[i+1][1])/2];ctx.quadraticCurveTo(...points[i],...end);}ctx.lineTo(...points.at(-1));}
function envelope(frame,count){return Array.from({length:count},(_,i)=>{const u=i/(count-1);const taper=Math.sin(Math.PI*u)**.75;return frame.level*(.32+.68*frame.bands[Math.round(u*31)])*taper;});}
function draw(view,frame){
  const {ctx,id,canvas}=view;ctx.setTransform(2,0,0,2,0,0);ctx.clearRect(0,0,340,72);ctx.strokeStyle=color;ctx.fillStyle=color;ctx.lineCap='round';ctx.lineJoin='round';
  if(variantSet?.draw?.(ctx,id,frame,view)){ctx.globalAlpha=1;canvas.dataset.energy=frame.level.toFixed(4);return;}
  const e=frame.level,a=envelope(frame,33),quiet=e<.001;
  switch(id){
    case 'pillars':
      for(let i=0;i<29;i++){const u=i/28,h=2+54*e*(.28+.72*frame.bands[Math.round(u*31)])*(.3+.7*Math.sin(Math.PI*u));bar(ctx,44+i*9,h,3,.3+.55*Math.sin(Math.PI*u));}break;
    case 'ribbon': {
      const top=a.map((v,i)=>[26+i*9,36-(1.2+v*29)*Math.sin(Math.PI*i/32)]);
      const bottom=a.map((v,i)=>[26+i*9,36+(1.2+v*29)*Math.sin(Math.PI*i/32)]).reverse();
      ctx.beginPath();smoothPath(ctx,top);smoothPath(ctx,bottom);ctx.closePath();ctx.globalAlpha=.18;ctx.fill();ctx.globalAlpha=.75;ctx.lineWidth=1.6;ctx.stroke();break;
    }
    case 'thread': {
      const points=Array.from({length:128},(_,i)=>{const u=i/127;const idle=2.5*Math.exp(-(((u-.5)*32)**2));return [24+u*292,36-(quiet?idle:frame.wave[i]*e*30*Math.sin(Math.PI*u)**.5)];});stroke(ctx,points,1.8,.8);break;
    }
    case 'twin':
      for(const sign of [-1,1]){const points=a.map((v,i)=>[28+i*8.875,36+sign*(2.5+v*26)*Math.sin(Math.PI*i/32)]);ctx.beginPath();smoothPath(ctx,points);ctx.lineWidth=1.8;ctx.globalAlpha=sign===-1?.85:.45;ctx.stroke();}break;
    case 'dots':
      for(let i=0;i<31;i++){const u=i/30,height=4*e*(.25+.75*frame.bands[Math.round(u*31)]);for(let j=-4;j<=4;j++)dot(ctx,35+i*9,36+j*6,1.55,j===0?.55+.2*e:.085+.715*clamp(height-Math.abs(j)+1));}break;
    case 'segments':
      for(let i=0;i<25;i++){const u=i/24,height=4*e*(.2+.8*frame.bands[Math.round(u*31)]);for(let j=-4;j<=4;j++){ctx.globalAlpha=j===0?.4+.3*e:.8*clamp(height-Math.abs(j)+1);ctx.fillRect(47+i*10,34.5+j*6,5,3);}}break;
    case 'capsules':
      for(let i=0;i<5;i++){const rest=[2,6,10,6,2][i];const height=rest+e*(16+38*frame.bands[3+i*6]);bar(ctx,122+i*24,Math.min(50,height),10,.4+Math.sin((i+1)/6*Math.PI)*.45);}break;
    case 'bloom':
      for(let i=0;i<40;i++){const angle=i/40*Math.PI*2;const band=frame.bands[Math.round(i/39*31)];const r=15;const extension=2+e*(5+12*band);stroke(ctx,[[170+Math.cos(angle)*r,36+Math.sin(angle)*r],[170+Math.cos(angle)*(r+extension),36+Math.sin(angle)*(r+extension)]],1.8,.4+.45*band*e);}break;
    case 'rings':
      for(let i=2;i>=0;i--){let band=0;for(let j=0;j<10;j++)band+=frame.bands[i*10+j]/10;ctx.beginPath();ctx.ellipse(170,36,12+i*7+e*(14+i*11+band*18),9+i*5+e*(4+band*7),0,0,Math.PI*2);ctx.lineWidth=1.6;ctx.globalAlpha=[.85,.5,.26][i];ctx.stroke();}break;
    case 'trail':
      for(let i=0;i<40;i++){const h=quiet?0:frame.history[i]*e;bar(ctx,33+i*7,1+58*h,2.5,.18+.7*(i/39));}dot(ctx,313,36,2.2,.8);break;
  }
  ctx.globalAlpha=1;canvas.dataset.energy=e.toFixed(4);
}
function readColor(){color=getComputedStyle(document.documentElement).getPropertyValue('--primary').trim();views.forEach(v=>draw(v,v.live?lastFrame:emptyFrame()));}
function setStatus(){
  document.querySelector('#input-status').textContent=statuses[mode];
  document.querySelector('#use-mic').textContent=mode==='mic'?'Microphone on':mode==='requesting'?'Requesting…':'Use microphone';
  document.querySelector('#use-mic').disabled=mode==='requesting'||mode==='mic';
  document.querySelector('#play-sample').textContent=mode==='sample'?'Restart sample':'Play sample';
  document.querySelector('#stop-input').disabled=mode==='idle';
  document.querySelectorAll('.source-label').forEach(el=>el.textContent=mode==='mic'?'live microphone':mode==='sample'?'sample input':'input stopped');
}
function clearSignal(){level=0;bands.fill(0);history.fill(0);lastFrame=emptyFrame();views.forEach(v=>draw(v,emptyFrame()));document.querySelector('#input-level').style.width='0%';document.querySelector('#signal-status').textContent='Quiet';}
function releaseInput(){
  requestGeneration++;
  if(stream){for(const track of stream.getTracks())track.stop();stream=null;}
  source?.disconnect();source=null;analyser=null;
  const closing=audioContext;audioContext=null;if(closing&&closing.state!=='closed')closing.close().catch(()=>{});
  clearSignal();
}
function stopInput(){releaseInput();mode='idle';setStatus();}
function startSample(){releaseInput();document.querySelector('#input-error').hidden=true;sampleStart=performance.now();mode='sample';setStatus();}
async function startMicrophone(){
  if(mode==='mic'||mode==='requesting')return;
  releaseInput();const generation=requestGeneration;mode='requesting';setStatus();document.querySelector('#input-error').hidden=true;
  let pendingStream=null,pendingContext=null;
  try{
    if(!navigator.mediaDevices?.getUserMedia)throw Object.assign(new Error('Unavailable'),{name:'UnsupportedError'});
    pendingStream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:false},video:false});
    if(generation!==requestGeneration){pendingStream.getTracks().forEach(track=>track.stop());return;}
    pendingContext=new AudioContext();await pendingContext.resume();
    if(generation!==requestGeneration){pendingStream.getTracks().forEach(track=>track.stop());await pendingContext.close();return;}
    stream=pendingStream;audioContext=pendingContext;analyser=audioContext.createAnalyser();analyser.fftSize=2048;analyser.smoothingTimeConstant=.55;
    frequencyData=new Uint8Array(analyser.frequencyBinCount);timeData=new Float32Array(analyser.fftSize);
    source=audioContext.createMediaStreamSource(stream);source.connect(analyser); // Intentionally no speaker/output connection.
    for(const track of stream.getTracks())track.addEventListener('ended',()=>{if(stream===pendingStream){stopInput();showError('The microphone disconnected. Reconnect it and choose Use microphone.');}});
    mode='mic';setStatus();
  }catch(error){
    pendingStream?.getTracks().forEach(track=>track.stop());
    if(pendingContext&&pendingContext.state!=='closed')pendingContext.close().catch(()=>{});
    if(generation!==requestGeneration)return;
    stopInput();
    const messages={NotAllowedError:'Microphone access was declined. Allow it in your browser, then retry; or choose Play sample.',NotFoundError:'No microphone was found. Connect one and retry, or choose Play sample.',NotReadableError:'The microphone could not be opened. Check whether another app is using it.',UnsupportedError:'Live input needs a browser with microphone support on localhost or HTTPS. You can still play the sample.'};
    showError(messages[error.name]||'The microphone could not start. Retry or choose Play sample.');
  }
}
function showError(message){const el=document.querySelector('#input-error');el.textContent=message;el.hidden=false;}

// The preview is a deterministic synthetic signal, not a recording or generated voice.
// Every phrase has a finite envelope and the 12-second cycle contains real zero-input gaps.
function sampleFrame(t){
  if(variantSet?.sampleFrame)return variantSet.sampleFrame(t);
  const seconds=t%12;
  const syllables=[[1,.23,.48],[1.45,.3,.8],[2,.2,.55],[2.48,.4,.9],[3.15,.22,.6],[4.7,.4,.4],[5.25,.24,.68],[5.8,.35,.95],[6.5,.21,.55],[8.2,.34,.65],[8.85,.28,.86],[9.4,.26,.46]];
  let energy=0;for(const [center,width,strength]of syllables){const d=Math.abs(seconds-center)/width;if(d<1)energy=Math.max(energy,strength*Math.cos(d*Math.PI/2)**.65);}
  const b=Float32Array.from({length:32},(_,i)=>clamp(.38+.27*Math.sin(i*.47+seconds*2.1)+.23*Math.cos(i*.21-seconds*1.6)));
  const w=Float32Array.from({length:128},(_,i)=>.65*Math.sin(i*.19+seconds*12)+.25*Math.sin(i*.54+seconds*17));
  return {energy,bands:b,wave:w};
}
function microphoneFrame(){
  analyser.getFloatTimeDomainData(timeData);analyser.getByteFrequencyData(frequencyData);
  let square=0;for(const v of timeData)square+=v*v;const rms=Math.sqrt(square/timeData.length);
  const sensitivity=Number(document.querySelector('#sensitivity').value);
  const floor=micFloor/sensitivity;
  const energy=rms<=floor?0:clamp((rms-floor)*sensitivity*7);
  const b=Float32Array.from({length:32},(_,i)=>{
    const low=80*(6000/80)**(i/32),high=80*(6000/80)**((i+1)/32);
    const from=Math.max(1,Math.floor(low*analyser.fftSize/audioContext.sampleRate));
    const to=Math.min(frequencyData.length,Math.max(from+1,Math.ceil(high*analyser.fftSize/audioContext.sampleRate)));
    let sum=0;for(let k=from;k<to;k++)sum+=frequencyData[k];return sum/Math.max(1,to-from)/255;
  });
  const w=Float32Array.from({length:128},(_,i)=>clamp(timeData[i*4]/Math.max(.02,rms*2.2),-1,1));
  return {energy,bands:b,wave:w};
}
function tick(now){
  rafId=requestAnimationFrame(tick);
  const dt=Math.min(.08,(now-lastTick)/1000||.016);lastTick=now;
  if(mode!=='sample'&&mode!=='mic')return;
  const raw=mode==='sample'?sampleFrame((now-sampleStart)/1000):microphoneFrame();
  const attack=.045,release=.15;level+=(raw.energy-level)*(1-Math.exp(-dt/(raw.energy>level?attack:release)));
  if(raw.energy===0&&level<.008)level=0;
  for(let i=0;i<32;i++)bands[i]+=(raw.bands[i]-bands[i])*(1-Math.exp(-dt/.07));
  if(now-lastHistory>65){lastHistory=now;if(level>.01){history.shift();history.push(level);}else history.fill(0);}
  lastFrame={level,bands,wave:raw.wave,history};
  const interval=reducedMotion.matches?250:32;
  if(now-lastPaint<interval)return;lastPaint=now;
  const visual=reducedMotion.matches?{...lastFrame,wave:Float32Array.from({length:128},(_,i)=>Math.sin(i*.18)*.7)}:lastFrame;
  views.forEach(view=>{if(view.live&&view.visible)draw(view,visual);});
  document.querySelector('#input-level').style.width=`${Math.round(level*100)}%`;
  document.querySelector('#signal-status').textContent=level>.03?(mode==='mic'?'Input detected':'Sample phrase'):'Quiet';
}
function updateMotion(){document.querySelector('#motion-note').textContent=reducedMotion.matches?'Reduced motion: stepped level updates, no flowing trace.':'Fast response, soft release. Silence returns to stillness.';}
document.querySelector('#use-mic').addEventListener('click',startMicrophone);
document.querySelectorAll('[data-mic]').forEach(button=>button.addEventListener('click',startMicrophone));
document.querySelector('#play-sample').addEventListener('click',startSample);
document.querySelector('#stop-input').addEventListener('click',stopInput);
document.querySelector('#sensitivity').addEventListener('input',event=>{document.querySelector('#sensitivity-value').textContent=Number(event.target.value).toFixed(1)+'×';});
document.querySelector('#theme-toggle').addEventListener('click',()=>{const dark=document.documentElement.dataset.theme!=='dark';document.documentElement.dataset.theme=dark?'dark':'light';document.querySelector('#theme-toggle').textContent=dark?'Light mode':'Dark mode';readColor();});
document.querySelector('#overview').addEventListener('click',event=>{const on=document.body.classList.toggle('overview-mode');event.currentTarget.setAttribute('aria-pressed',String(on));event.currentTarget.textContent=on?'Full component view':'Waveform overview';views.forEach(v=>draw(v,v.live?lastFrame:emptyFrame()));});
document.addEventListener('keydown',event=>{if(event.key==='Escape')stopInput();if(event.ctrlKey&&event.shiftKey&&event.code==='Space'&&!event.repeat){event.preventDefault();mode==='mic'||mode==='requesting'?stopInput():startMicrophone();}});
document.addEventListener('visibilitychange',()=>{if(document.hidden)stopInput();});
window.addEventListener('pagehide',()=>{releaseInput();cancelAnimationFrame(rafId);});
reducedMotion.addEventListener('change',updateMotion);
readColor();updateMotion();if(!reducedMotion.matches)startSample();else setStatus();rafId=requestAnimationFrame(tick);

// Deterministic design-review hooks: rendering only, no microphone permission bypass.
window.waveformReview={
  designs:designs.map(({id,name})=>({id,name})),
  get mode(){return mode;},get level(){return level;},
  get tracks(){return stream?stream.getTracks().map(t=>t.readyState):[];},
  stop:stopInput,
  frameAt(seconds){stopInput();const raw=sampleFrame(seconds);const frame={snapshot:true,level:raw.energy,bands:raw.bands,wave:raw.wave,history:Array.from({length:40},(_,i)=>sampleFrame(seconds-(39-i)*.065).energy)};views.forEach(v=>draw(v,v.live?frame:emptyFrame()));lastFrame=frame;document.querySelector('#input-status').textContent='Paused sample · comparison snapshot';document.querySelector('#signal-status').textContent='Reference frame';document.querySelectorAll('.source-label').forEach(el=>el.textContent='sample frame');},
};
