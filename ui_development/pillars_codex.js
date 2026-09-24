'use strict';

// Five motion treatments of the SAME 29 pillars. This extension reuses the
// existing comparison's microphone lifecycle, themes, and recorder markup.
(() => {
  const clamp=(v,min=0,max=1)=>Math.max(min,Math.min(max,v));
  const designs=[
    {id:'thread-envelope',name:'Thread envelope',note:'A flowing wave drawn with fixed-center pillars.',motion:'Individual heights blend the sampled audio waveform with frequency detail. Closest to Fine Thread, with a stable centerline.'},
    {id:'floating-thread',name:'Floating thread',note:'The pillars themselves trace the rise and fall.',motion:'Pillars grow with loudness and move slightly above or below center along the signed waveform. Frequency energy changes each pillar’s height.'},
    {id:'frequency-lanes',name:'Frequency lanes',note:'Lower sounds on the left. Higher sounds on the right.',motion:'Each pillar covers a different frequency band. Peaks migrate across the row as spectral energy changes, with a small waveform fluctuation.'},
    {id:'mirrored-voice',name:'Mirrored voice',note:'A balanced wave, unfolding from the center.',motion:'Lower frequencies drive the middle pillars; higher frequencies drive the outer pillars. Mirrored waveform detail produces a symmetric contour.'},
    {id:'woven-contour',name:'Woven contour',note:'Broad spectral peaks with a finer moving contour.',motion:'A blend of smoothed frequency peaks and waveform lobes. Per-pillar attack/release makes the clusters flow without a clock-driven oscillation.'},
  ];
  function interpolate(values,x){const at=clamp(x,0,values.length-1),lo=Math.floor(at),hi=Math.min(values.length-1,lo+1);return values[lo]+(values[hi]-values[lo])*(at-lo);}
  function smoothSample(values,x,radius=2){let total=0,weight=0;for(let k=-radius;k<=radius;k++){const w=radius+1-Math.abs(k);total+=interpolate(values,x+k)*w;weight+=w;}return total/weight;}

  // Pure geometry, separately testable: volume scales height; different bands
  // and waveform samples select which of the fixed pillars are emphasized.
  function geometry(id,frame){
    const level=clamp(frame.level);
    return Array.from({length:29},(_,i)=>{
      const u=i/28,edge=.3+.7*Math.sin(Math.PI*u);
      const band=smoothSample(frame.bands,u*31,1);
      const signed=smoothSample(frame.wave,u*127,2);
      const wave=Math.abs(signed);
      let height=2,center=36;
      if(id==='thread-envelope'){
        height+=54*level*(.06+.67*wave+.27*band)*edge;
      }else if(id==='floating-thread'){
        height+=level*(7+25*band+13*wave)*edge;
        center-=signed*level*10*edge;
      }else if(id==='frequency-lanes'){
        height+=57*level*(.025+.84*band+.135*wave);
      }else if(id==='mirrored-voice'){
        const distance=Math.abs(i-14)/14;
        const mirroredBand=smoothSample(frame.bands,distance*31,1);
        const mirroredWave=Math.abs(smoothSample(frame.wave,distance*127,2));
        height+=55*level*(.04+.65*mirroredBand+.31*mirroredWave)*(.45+.55*Math.sin(Math.PI*u));
      }else if(id==='woven-contour'){
        const broad=smoothSample(frame.bands,u*31,3);
        const lobe=Math.abs(smoothSample(frame.wave,u*127,4));
        height+=56*level*(.035+.49*broad+.475*lobe)*(.6+.4*Math.sin(Math.PI*u));
        center-=signed*level*3;
      }
      return {x:44+i*9,height,center,width:3,opacity:.3+.55*Math.sin(Math.PI*u)};
    });
  }

  function draw(ctx,id,frame,view){
    const target=geometry(id,frame);
    // Default pixels are identical to Quiet Pillars. No animation at rest.
    const immediate=frame.snapshot||frame.level===0||matchMedia('(prefers-reduced-motion: reduce)').matches;
    const now=performance.now();
    const dt=Math.min(.15,Math.max(.008,(now-(view.pillarTime||now-32))/1000));view.pillarTime=now;
    if(!view.pillarState||immediate)view.pillarState=target.map(v=>({...v}));
    const attack=id==='woven-contour'?.09:.045;
    const release=id==='woven-contour'?.2:.11;
    for(let i=0;i<target.length;i++){
      const p=view.pillarState[i],t=target[i];
      const factor=immediate?1:1-Math.exp(-dt/(t.height>p.height?attack:release));
      p.height+=(t.height-p.height)*factor;p.center+=(t.center-p.center)*factor;
      ctx.globalAlpha=t.opacity;ctx.lineWidth=t.width;ctx.beginPath();ctx.moveTo(t.x,p.center-p.height/2);ctx.lineTo(t.x,p.center+p.height/2);ctx.stroke();
    }
    return true;
  }

  let pattern='phrasing';
  function sampleFrame(t){
    const seconds=((t%12)+12)%12;
    let energy=0,frequency=180;
    if(pattern==='volume'){
      // A constant tone profile at four progressively louder levels.
      const step=Math.floor(seconds/3);const within=seconds%3;
      energy=within>.25&&within<2.65?[.13,.32,.58,.9][step]:0;frequency=220;
    }else if(pattern==='pitch'){
      // Equal loudness; shift the fundamental and its harmonics across bands.
      energy=seconds>.5&&seconds<10.6?.72:0;
      frequency=100*Math.pow(16,clamp((seconds-.5)/10));
    }else if(pattern==='phrasing'){
      const syllables=[[.8,.32,.45],[1.45,.38,.78],[2.15,.3,.57],[2.8,.43,.92],[4.25,.32,.55],[4.95,.45,.78],[5.65,.32,.43],[7.15,.35,.6],[7.85,.32,.88],[8.6,.4,.72],[9.35,.26,.5]];
      for(const [center,width,amount]of syllables){const distance=Math.abs(seconds-center)/width;if(distance<1)energy=Math.max(energy,amount*Math.cos(distance*Math.PI/2)**.6);}
      frequency=145+90*Math.sin(seconds*1.65)+130*(.5+.5*Math.sin(seconds*.66));
    }
    const spectrum=Float32Array.from({length:32},(_,i)=>{
      const hz=80*Math.pow(6000/80,(i+.5)/32);let value=.02;
      for(let harmonic=1;harmonic<=5;harmonic++){const distance=Math.log2(hz/(frequency*harmonic));value+=Math.exp(-distance*distance/(2*.16**2))/Math.pow(harmonic,.65);}
      return clamp(value);
    });
    // This is a labeled synthetic preview. Live mode supplies real samples.
    const phase=pattern==='volume'?0:seconds*2.8;
    const cycles=1.6+Math.log2(frequency/100)*1.15;
    const wave=Float32Array.from({length:128},(_,i)=>{
      const angle=i/127*Math.PI*2*cycles+phase;
      return Math.sin(angle)*.68+Math.sin(angle*2+.5)*.2+Math.sin(angle*3)*.1;
    });
    return {energy,bands:spectrum,wave};
  }
  window.waveformVariantSet={designs,draw,sampleFrame};
  window.pillarsReview={geometry,setPattern(value){pattern=value;},get pattern(){return pattern;}};
  document.querySelector('#sample-pattern').addEventListener('change',event=>{
    pattern=event.target.value;
    if(window.waveformReview?.mode==='mic'){
      document.querySelector('#sample-description').textContent='Sample pattern selected. Click Play sample to switch away from your microphone.';
    }else{
      document.querySelector('#sample-description').textContent='Synthetic input · no audio playback. The same signal drives every sample.';
      document.querySelector('#play-sample').click();
    }
  });
})();
