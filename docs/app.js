/* MatterMind project showcase. All graphics are illustrative; no simulations run here. */
(() => {
  'use strict';
  function connectTabs(tablist) {
    const tabs = [...tablist.querySelectorAll('[role="tab"]')];
    function select(tab, focus = false) {
      tabs.forEach((item) => {
        const active = item === tab;
        item.setAttribute('aria-selected', String(active));
        item.tabIndex = active ? 0 : -1;
        const panel = document.getElementById(item.getAttribute('aria-controls'));
        if (panel) panel.hidden = !active;
      });
      if (focus) tab.focus();
    }
    tabs.forEach((tab, index) => {
      tab.addEventListener('click', () => select(tab));
      tab.addEventListener('keydown', (event) => {
        let next;
        if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
        if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
        if (event.key === 'Home') next = 0;
        if (event.key === 'End') next = tabs.length - 1;
        if (next !== undefined) { event.preventDefault(); select(tabs[next], true); }
      });
    });
  }
  document.querySelectorAll('[role="tablist"]').forEach(connectTabs);

  const copyButton = document.getElementById('copy-citation');
  copyButton?.addEventListener('click', async () => {
    const citation = document.getElementById('bibtex').textContent;
    const status = document.getElementById('copy-status');
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(citation);
      status.textContent = 'BibTeX copied to your clipboard.';
      copyButton.innerHTML = 'Copied <span aria-hidden="true">✓</span>';
      setTimeout(() => { copyButton.innerHTML = 'Copy BibTeX <span aria-hidden="true">⧉</span>'; }, 2500);
    } catch {
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(document.getElementById('bibtex'));
      selection.removeAllRanges(); selection.addRange(range);
      status.textContent = 'Citation selected. Press Ctrl+C (Windows) or Command+C (Mac) to copy, or download the .bib file.';
    }
  });

  const canvas = document.getElementById('crystal-canvas');
  const context = canvas?.getContext('2d');
  if (!context) return;
  const motionButton = document.getElementById('motion-toggle');
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  let paused = reducedMotion.matches;
  let visible = true;
  let width = 0, height = 0, rotationY = -0.57, rotationX = 0.4;
  let dragging = false, lastX = 0, lastY = 0, lastFrame = 0, frame = 0;
  const points = [], edges = [];
  // A deliberately abstract cubic lattice, not an experimental or calculated structure.
  for (let x = -1; x <= 1; x++) for (let y = -1; y <= 1; y++) for (let z = -1; z <= 1; z++) {
    points.push({ x, y, z, kind: (x + y + z + 3) % 2, size: x === 0 && y === 0 && z === 0 ? 1.28 : 1 });
  }
  points.forEach((point, index) => points.forEach((other, next) => {
    if (next > index && Math.abs(point.x - other.x) + Math.abs(point.y - other.y) + Math.abs(point.z - other.z) === 1) edges.push([index, next]);
  }));
  function resize() {
    const rect = canvas.getBoundingClientRect();
    width = rect.width; height = rect.height;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0); draw();
  }
  function project(point) {
    const sy = Math.sin(rotationY), cy = Math.cos(rotationY), sx = Math.sin(rotationX), cx = Math.cos(rotationX);
    const x = point.x * cy + point.z * sy;
    const z = point.z * cy - point.x * sy;
    const y = point.y * cx - z * sx;
    const depth = point.y * sx + z * cx;
    const scale = Math.min(width * 0.185, height * 0.18);
    const perspective = 5.8 / (5.8 + depth);
    return { x: width * .49 + x * scale * perspective, y: height * .48 + y * scale * perspective, depth, perspective, kind: point.kind, size: point.size };
  }
  function draw() {
    if (!width || !height) return;
    context.clearRect(0, 0, width, height);
    const projected = points.map(project);
    const shadow = context.createRadialGradient(width * .48, height * .80, 0, width * .48, height * .80, width * .29);
    shadow.addColorStop(0, 'rgba(59,105,80,.11)'); shadow.addColorStop(1, 'rgba(59,105,80,0)');
    context.save(); context.translate(0, height * .57); context.scale(1, .28); context.fillStyle = shadow; context.fillRect(0, 0, width, height); context.restore();
    // Draw far planes first, with light connections keeping the lattice legible.
    [...edges].sort((a, b) => (projected[b[0]].depth + projected[b[1]].depth) - (projected[a[0]].depth + projected[a[1]].depth)).forEach(([a, b]) => {
      const p = projected[a], q = projected[b];
      const depth = (p.depth + q.depth) / 2;
      context.beginPath(); context.moveTo(p.x, p.y); context.lineTo(q.x, q.y);
      context.strokeStyle = `rgba(61,95,108,${Math.max(.15, .48 - depth * .10)})`; context.lineWidth = depth > 0 ? .8 : 1.2; context.stroke();
    });
    [...projected].sort((a, b) => b.depth - a.depth).forEach((point) => {
      const radius = Math.max(4, Math.min(width, height) * .020) * point.perspective * point.size;
      context.beginPath(); context.arc(point.x + 1.5, point.y + 3, radius * 1.04, 0, Math.PI * 2); context.fillStyle = 'rgba(24,52,64,.07)'; context.fill();
      const fill = context.createRadialGradient(point.x - radius * .34, point.y - radius * .4, radius * .03, point.x, point.y, radius);
      if (point.kind) { fill.addColorStop(0, '#84b9bc'); fill.addColorStop(.33, '#4b8e86'); fill.addColorStop(1, '#174951'); }
      else { fill.addColorStop(0, '#a9b9f4'); fill.addColorStop(.34, '#567ade'); fill.addColorStop(1, '#234ba4'); }
      context.globalAlpha = Math.max(.48, .86 - point.depth * .08);
      context.beginPath(); context.arc(point.x, point.y, radius, 0, Math.PI * 2); context.fillStyle = fill; context.fill(); context.globalAlpha = 1;
    });
  }
  function animate(timestamp) {
    frame = 0;
    if (paused || !visible || document.hidden) { lastFrame = 0; return; }
    const elapsed = lastFrame ? Math.min(timestamp - lastFrame, 40) : 16;
    lastFrame = timestamp;
    if (!dragging) rotationY += elapsed * .00007;
    draw(); frame = requestAnimationFrame(animate);
  }
  function start() { if (!frame && !paused && visible && !document.hidden) frame = requestAnimationFrame(animate); }
  function syncMotion() {
    motionButton.setAttribute('aria-pressed', String(paused));
    motionButton.setAttribute('aria-label', paused ? 'Resume lattice rotation' : 'Pause lattice rotation');
    motionButton.innerHTML = `<span aria-hidden="true">${paused ? '▶' : 'Ⅱ'}</span>`;
    if (paused && frame) { cancelAnimationFrame(frame); frame = 0; lastFrame = 0; } else start();
  }
  motionButton.addEventListener('click', () => { paused = !paused; syncMotion(); });
  reducedMotion.addEventListener('change', (event) => { paused = event.matches; syncMotion(); });
  canvas.addEventListener('pointerdown', (event) => { dragging = true; lastX = event.clientX; lastY = event.clientY; canvas.setPointerCapture(event.pointerId); });
  canvas.addEventListener('pointermove', (event) => {
    if (!dragging) return;
    rotationY += (event.clientX - lastX) * .008;
    rotationX = Math.max(-1.1, Math.min(1.1, rotationX + (event.clientY - lastY) * .006));
    lastX = event.clientX; lastY = event.clientY; draw();
  });
  ['pointerup', 'pointercancel', 'lostpointercapture'].forEach((name) => canvas.addEventListener(name, () => { dragging = false; }));
  canvas.addEventListener('keydown', (event) => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
    event.preventDefault();
    if (event.key === 'ArrowLeft') rotationY -= .12;
    if (event.key === 'ArrowRight') rotationY += .12;
    if (event.key === 'ArrowUp') rotationX = Math.max(-1.1, rotationX - .10);
    if (event.key === 'ArrowDown') rotationX = Math.min(1.1, rotationX + .10);
    draw();
  });
  document.addEventListener('visibilitychange', start);
  new IntersectionObserver((entries) => { visible = entries[0].isIntersecting; start(); }, { threshold: .05 }).observe(canvas);
  new ResizeObserver(resize).observe(canvas);
  syncMotion();
})();
