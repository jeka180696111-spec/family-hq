// ═══════════════════════════════════════════════════════════════
// GESTURES — touch gestures for mobile UX
// ═══════════════════════════════════════════════════════════════

// ── Swipe right from left edge → open sidebar ────────────────
export function initEdgeSwipe(onOpen) {
  let startX = 0, startY = 0, tracking = false;
  document.addEventListener('touchstart', e => {
    const t = e.touches[0];
    if (t.clientX > 40) return; // only from left edge
    startX = t.clientX; startY = t.clientY; tracking = true;
  }, { passive: true });
  document.addEventListener('touchend', e => {
    if (!tracking) return;
    tracking = false;
    const t = e.changedTouches[0];
    const dx = t.clientX - startX;
    const dy = Math.abs(t.clientY - startY);
    if (dx > 60 && dy < 40) onOpen();
  }, { passive: true });
}

// ── Long press → callback(element) ───────────────────────────
export function addLongPress(el, callback, ms = 500) {
  let timer = null;
  el.addEventListener('touchstart', e => {
    timer = setTimeout(() => {
      timer = null;
      callback(el);
    }, ms);
  }, { passive: true });
  el.addEventListener('touchend',   () => clearTimeout(timer));
  el.addEventListener('touchmove',  () => clearTimeout(timer));
  el.addEventListener('touchcancel',() => clearTimeout(timer));
}

// ── Swipe left on element → show delete overlay ──────────────
const SWIPE_THRESHOLD = 60;
const SWIPE_MAX_Y = 30;

export function addSwipeDelete(el, onDelete, labelText = 'Видалити') {
  let startX = 0, startY = 0, swiping = false, revealed = false;

  // Create delete overlay (absolutely positioned behind el)
  const overlay = document.createElement('div');
  overlay.className = 'swipe-delete-overlay';
  overlay.innerHTML = `<i class="ti ti-trash"></i> ${labelText}`;
  overlay.style.cssText = `
    position:absolute; right:0; top:0; bottom:0;
    background:var(--c-red); color:#fff;
    display:flex; align-items:center; gap:6px;
    padding:0 20px; border-radius:0 12px 12px 0;
    font-size:13px; font-weight:700;
    opacity:0; pointer-events:none;
    transition:opacity .2s;
  `;
  // Wrap el in a relative container if not already
  const parent = el.parentElement;
  if (!parent) return;
  if (getComputedStyle(parent).position === 'static') {
    parent.style.position = 'relative';
  }
  parent.appendChild(overlay);

  el.style.transition = 'transform .2s';
  el.style.willChange = 'transform';

  el.addEventListener('touchstart', e => {
    startX = e.touches[0].clientX;
    startY = e.touches[0].clientY;
    swiping = false;
    el.style.transition = '';
  }, { passive: true });

  el.addEventListener('touchmove', e => {
    const dx = e.touches[0].clientX - startX;
    const dy = Math.abs(e.touches[0].clientY - startY);
    if (dy > SWIPE_MAX_Y && !swiping) return;
    if (dx < -10) {
      swiping = true;
      const move = Math.max(dx, -120);
      el.style.transform = `translateX(${move}px)`;
      overlay.style.opacity = Math.min(1, Math.abs(move) / 80).toString();
      overlay.style.pointerEvents = 'none';
    }
  }, { passive: true });

  el.addEventListener('touchend', e => {
    const dx = e.changedTouches[0].clientX - startX;
    el.style.transition = 'transform .25s';
    if (dx < -SWIPE_THRESHOLD) {
      // Snap to reveal state
      el.style.transform = 'translateX(-80px)';
      overlay.style.opacity = '1';
      overlay.style.pointerEvents = 'auto';
      revealed = true;
    } else {
      // Snap back
      el.style.transform = '';
      overlay.style.opacity = '0';
      overlay.style.pointerEvents = 'none';
      revealed = false;
    }
  }, { passive: true });

  overlay.addEventListener('click', async () => {
    overlay.style.pointerEvents = 'none';
    el.style.transform = '';
    overlay.style.opacity = '0';
    revealed = false;
    await onDelete();
  });

  // Tap elsewhere to close
  document.addEventListener('touchstart', e => {
    if (revealed && !el.contains(e.target) && !overlay.contains(e.target)) {
      el.style.transition = 'transform .25s';
      el.style.transform = '';
      overlay.style.opacity = '0';
      overlay.style.pointerEvents = 'none';
      revealed = false;
    }
  }, { passive: true });
}
