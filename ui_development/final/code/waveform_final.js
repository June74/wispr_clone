/* Frequency Lanes on Quiet Pillars — the dictation card's waveform.
   Spec: ui_development/audio_waveform_component.md (reference source: ui_development/pillars_codex.js, waveforms_codex.js)

   At rest: 29 still pillars (2px tall). While listening, loudness sets height and the
   frequency spectrum decides WHICH pillars rise (low → left, high → right), with a small
   waveform term for texture. Silence settles back to the exact resting pixels; there is
   no idle/looping animation, and the draw loop stops once everything is still.

   Microphone audio is analysed locally only: nothing is stored, uploaded or played. */
window.FrequencyLanes = (() => {
  const N = 29, W = 340, H = 72, SCALE = 2, CENTER = 36, REST = 2;
  // Sensitivity doubled from the spec default (1.5×) to 3×, the top of the spec's 0.5–3× range.
  // Higher sensitivity lowers the silence threshold (0.012 / 3 = 0.004) and scales loudness 2× harder.
  const MIC_FLOOR = 0.012, SENSITIVITY = 3;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');

  const clamp = (v, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, v));
  function interpolate(values, position) {
    const at = clamp(position, 0, values.length - 1);
    const low = Math.floor(at), high = Math.min(values.length - 1, low + 1);
    return values[low] + (values[high] - values[low]) * (at - low);
  }
  function smoothSample(values, position, radius) {
    let sum = 0, weights = 0;
    for (let o = -radius; o <= radius; o++) {
      const w = radius + 1 - Math.abs(o);
      sum += interpolate(values, position + o) * w; weights += w;
    }
    return sum / weights;
  }
  // Selected geometry (spec § "Selected geometry and animation formula")
  function targets(level, bands, wave) {
    return Array.from({ length: N }, (_, i) => {
      const u = i / 28;
      const band = smoothSample(bands, u * 31, 1);
      const waveform = Math.abs(smoothSample(wave, u * 127, 2));
      return REST + 57 * clamp(level) * (0.025 + 0.84 * band + 0.135 * waveform);
    });
  }
  const X = (i) => 44 + 9 * i;
  const OPACITY = Array.from({ length: N }, (_, i) => 0.30 + 0.55 * Math.sin(Math.PI * i / 28));
  const ZERO_BANDS = new Float32Array(32), ZERO_WAVE = new Float32Array(128);
  const REDUCED_TRACE = Float32Array.from({ length: 128 }, (_, i) => Math.sin(i * 0.18) * 0.7);

  // Deterministic synthetic phrase (same as the reference sample): finite syllable
  // envelopes with real silent gaps. Used only when the microphone is unavailable.
  function sampleFrame(t) {
    const s = t % 12;
    const syl = [[1, .23, .48], [1.45, .3, .8], [2, .2, .55], [2.48, .4, .9], [3.15, .22, .6], [4.7, .4, .4], [5.25, .24, .68], [5.8, .35, .95], [6.5, .21, .55], [8.2, .34, .65], [8.85, .28, .86], [9.4, .26, .46]];
    let energy = 0;
    for (const [c, w, k] of syl) { const d = Math.abs(s - c) / w; if (d < 1) energy = Math.max(energy, k * Math.cos(d * Math.PI / 2) ** 0.65); }
    const bands = Float32Array.from({ length: 32 }, (_, i) => clamp(.38 + .27 * Math.sin(i * .47 + s * 2.1) + .23 * Math.cos(i * .21 - s * 1.6)));
    const wave = Float32Array.from({ length: 128 }, (_, i) => .65 * Math.sin(i * .19 + s * 12) + .25 * Math.sin(i * .54 + s * 17));
    return { energy, bands, wave };
  }

  function create(canvas, { color }) {
    canvas.width = W * SCALE; canvas.height = H * SCALE;
    const g = canvas.getContext('2d');
    g.setTransform(SCALE, 0, 0, SCALE, 0, 0);

    let mode = 'idle';                     // idle | requesting | mic | sample
    let level = 0, bands = new Float32Array(32), heights = new Array(N).fill(REST);
    let stream = null, audio = null, analyser = null, source = null, freq, time, generation = 0;
    let raf = 0, lastTick = 0, lastPaint = 0, sampleStart = 0;

    function paint() {
      g.clearRect(0, 0, W, H);
      g.strokeStyle = color(); g.lineCap = 'round'; g.lineWidth = 3;
      for (let i = 0; i < N; i++) {
        g.globalAlpha = OPACITY[i];
        g.beginPath(); g.moveTo(X(i), CENTER - heights[i] / 2); g.lineTo(X(i), CENTER + heights[i] / 2); g.stroke();
      }
      g.globalAlpha = 1;
    }

    function micFrame() {
      analyser.getFloatTimeDomainData(time); analyser.getByteFrequencyData(freq);
      let sq = 0; for (const v of time) sq += v * v;
      const rms = Math.sqrt(sq / time.length), floor = MIC_FLOOR / SENSITIVITY;
      const energy = rms <= floor ? 0 : clamp((rms - floor) * SENSITIVITY * 7);
      const b = Float32Array.from({ length: 32 }, (_, i) => {   // 32 log bands, ~80 Hz – 6 kHz
        const lo = 80 * (6000 / 80) ** (i / 32), hi = 80 * (6000 / 80) ** ((i + 1) / 32);
        const from = Math.max(1, Math.floor(lo * analyser.fftSize / audio.sampleRate));
        const to = Math.min(freq.length, Math.max(from + 1, Math.ceil(hi * analyser.fftSize / audio.sampleRate)));
        let sum = 0; for (let k = from; k < to; k++) sum += freq[k];
        return sum / Math.max(1, to - from) / 255;
      });
      const w = Float32Array.from({ length: 128 }, (_, i) => clamp(time[i * 4] / Math.max(.02, rms * 2.2), -1, 1));
      return { energy, bands: b, wave: w };
    }

    function tick(now) {
      const dt = Math.min(0.08, (now - lastTick) / 1000 || 0.016); lastTick = now;
      const raw = mode === 'mic' ? micFrame()
        : mode === 'sample' ? sampleFrame((now - sampleStart) / 1000 + 0.8)
        : { energy: 0, bands: ZERO_BANDS, wave: ZERO_WAVE };
      // overall level: 45 ms attack / 150 ms release; snap to exact rest below 0.008
      level += (raw.energy - level) * (1 - Math.exp(-dt / (raw.energy > level ? 0.045 : 0.150)));
      if (raw.energy === 0 && level < 0.008) level = 0;
      for (let i = 0; i < 32; i++) bands[i] += (raw.bands[i] - bands[i]) * (1 - Math.exp(-dt / 0.07));

      const interval = reduced.matches ? 250 : 32;           // ~4 fps stepped vs ~30 fps
      if (now - lastPaint >= interval) {
        const pdt = Math.min(0.15, Math.max(0.008, (now - lastPaint) / 1000)); lastPaint = now;
        const t = targets(level, bands, reduced.matches ? REDUCED_TRACE : raw.wave);
        const immediate = level === 0 || reduced.matches;
        for (let i = 0; i < N; i++) {
          const k = immediate ? 1 : 1 - Math.exp(-pdt / (t[i] > heights[i] ? 0.045 : 0.110));
          heights[i] += (t[i] - heights[i]) * k;
        }
        paint();
      }
      // stop the loop once idle and fully still — no perpetual animation at rest
      if (mode === 'idle' && level === 0 && heights.every((h) => h === REST)) { raf = 0; return; }
      raf = requestAnimationFrame(tick);
    }
    const run = () => { if (!raf) { lastTick = lastPaint = performance.now(); raf = requestAnimationFrame(tick); } };

    function release() {
      generation++;
      stream?.getTracks().forEach((t) => t.stop()); stream = null;
      source?.disconnect(); source = null; analyser = null;
      if (audio && audio.state !== 'closed') audio.close().catch(() => {});
      audio = null;
    }

    /** Start listening. Resolves to 'mic' or 'sample' (fallback when the mic is unavailable). */
    async function start() {
      release();
      const gen = generation;
      mode = 'requesting'; run();
      let s = null, ctx = null;
      try {
        if (!navigator.mediaDevices?.getUserMedia) throw new Error('unsupported');
        s = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: false }, video: false });
        if (gen !== generation) { s.getTracks().forEach((t) => t.stop()); return 'cancelled'; }
        ctx = new AudioContext(); await ctx.resume();
        if (gen !== generation) { s.getTracks().forEach((t) => t.stop()); ctx.close(); return 'cancelled'; }
        stream = s; audio = ctx;
        analyser = audio.createAnalyser(); analyser.fftSize = 2048; analyser.smoothingTimeConstant = 0.55;
        freq = new Uint8Array(analyser.frequencyBinCount); time = new Float32Array(analyser.fftSize);
        source = audio.createMediaStreamSource(stream); source.connect(analyser);   // no speaker output
        mode = 'mic';
      } catch {
        s?.getTracks().forEach((t) => t.stop());
        if (ctx && ctx.state !== 'closed') ctx.close().catch(() => {});
        if (gen !== generation) return 'cancelled';
        sampleStart = performance.now(); mode = 'sample';
      }
      run();
      return mode;
    }
    /** Stop listening; the pillars settle back to rest on their own. */
    function stop() { release(); mode = 'idle'; paint(); run(); }

    document.addEventListener('visibilitychange', () => { if (document.hidden && (mode === 'mic' || mode === 'requesting')) stop(); });
    window.addEventListener('pagehide', release);
    paint();

    return {
      start, stop,
      redraw: paint,                                     // e.g. after a theme or state colour change
      heights: () => heights.slice(),
      state: () => ({ mode, level, heights: heights.slice() }),
    };
  }

  return { create, REST, N, SENSITIVITY };
})();
