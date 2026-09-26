const COUNT = 29;
export function createWaveform(canvas, color = () => '#745689') {
  const ctx = canvas.getContext('2d');
  let bands = Array(12).fill(0);
  let active = false;
  function draw() {
    const width = canvas.width = 680;
    const height = canvas.height = 144;
    ctx.clearRect(0, 0, width, height);
    ctx.strokeStyle = color(); ctx.lineWidth = 6; ctx.lineCap = 'round';
    for (let i = 0; i < COUNT; i++) {
      const sample = bands[Math.min(11, Math.floor(i * 12 / COUNT))] ?? 0;
      const h = active ? 4 + Math.max(0, Math.min(1, sample)) * 104 : 4;
      const x = 88 + i * 18;
      ctx.globalAlpha = 0.3 + 0.55 * Math.sin(Math.PI * i / (COUNT - 1));
      ctx.beginPath(); ctx.moveTo(x, height / 2 - h / 2); ctx.lineTo(x, height / 2 + h / 2); ctx.stroke();
    }
    ctx.globalAlpha = 1;
  }
  function update(levelBands, running) { bands = Array.isArray(levelBands) && levelBands.length === 12 ? levelBands.map((n) => Math.max(0, Math.min(1, Number(n) || 0))) : Array(12).fill(0); active = Boolean(running); draw(); }
  draw();
  return { update, redraw: draw };
}
