// ═══════════════════════════════════════════════════════════════
// RECEIPT SCANNER — фото чека та QR-сканер
// ═══════════════════════════════════════════════════════════════

import { openBottomSheet, closeModal } from './modals.js';
import { showToast } from './utils.js';

// ── Вибір способу сканування ────────────────────────────────
export function openScannerChoice() {
  const content = `
    <div class="scanner-choice">
      <button class="scanner-choice-btn" id="sc-photo">
        <i class="ti ti-camera"></i>
        <div>
          <div>📷 Фото чека</div>
          <div class="scanner-choice-desc">Сфотографуй чек — AI розпізнає суму</div>
        </div>
      </button>
      <button class="scanner-choice-btn" id="sc-qr">
        <i class="ti ti-qrcode"></i>
        <div>
          <div>🔲 QR код</div>
          <div class="scanner-choice-desc">Відскануй QR-код з чека</div>
        </div>
      </button>
    </div>
  `;

  const modalId = openBottomSheet({
    title: 'Сканер чека',
    content,
    onOpen: (wrap) => {
      wrap.querySelector('#sc-photo').addEventListener('click', () => {
        closeModal(modalId);
        openReceiptPhoto();
      });
      wrap.querySelector('#sc-qr').addEventListener('click', () => {
        closeModal(modalId);
        openQRScanner();
      });
    },
  });
}

// ── Фото чека ────────────────────────────────────────────────
export function openReceiptPhoto() {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/*';
  input.capture = 'environment';
  input.style.display = 'none';
  document.body.appendChild(input);

  input.addEventListener('change', async () => {
    const file = input.files?.[0];
    document.body.removeChild(input);
    if (!file) return;

    showToast('Аналізую чек...');

    try {
      const base64 = await readFileAsBase64(file);
      const response = await fetch('/api/analyze-receipt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          image: base64.split(',')[1],
          mediaType: file.type,
        }),
      });

      const result = await response.json();

      if (result.error) {
        showToast('Помилка: ' + result.error);
        return;
      }

      await openExpenseDialog({
        amount: result.amount,
        store: result.store,
        date: result.date,
        category: result.category,
      });
    } catch (e) {
      showToast('Помилка аналізу чека: ' + e.message);
    }
  });

  input.addEventListener('cancel', () => {
    document.body.removeChild(input);
  });

  input.click();
}

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

// ── QR сканер ────────────────────────────────────────────────
export function openQRScanner() {
  // Динамічно завантажуємо jsQR
  const loadJsQR = () => new Promise((resolve, reject) => {
    if (window.jsQR) { resolve(window.jsQR); return; }
    const script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/jsqr@1.4.0/dist/jsQR.min.js';
    script.onload = () => resolve(window.jsQR);
    script.onerror = () => reject(new Error('Не вдалося завантажити jsQR'));
    document.head.appendChild(script);
  });

  // Створюємо overlay
  const overlay = document.createElement('div');
  overlay.className = 'scanner-overlay';
  overlay.innerHTML = `
    <button class="scanner-close" id="scanner-close-btn">✕</button>
    <video class="scanner-video" id="scanner-video" autoplay playsinline></video>
    <div class="scanner-viewfinder"></div>
    <div class="scanner-hint">Наведіть камеру на QR код</div>
  `;
  document.body.appendChild(overlay);

  let stream = null;
  let animFrameId = null;

  const closeScanner = () => {
    if (animFrameId) cancelAnimationFrame(animFrameId);
    if (stream) stream.getTracks().forEach(t => t.stop());
    if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
  };

  overlay.querySelector('#scanner-close-btn').addEventListener('click', closeScanner);

  (async () => {
    try {
      const jsQR = await loadJsQR();

      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment' },
      });

      const video = overlay.querySelector('#scanner-video');
      video.srcObject = stream;
      await video.play();

      const canvas = document.createElement('canvas');
      const ctx = canvas.getContext('2d');

      const scan = () => {
        if (!overlay.parentNode) return;
        if (video.readyState === video.HAVE_ENOUGH_DATA) {
          canvas.width = video.videoWidth;
          canvas.height = video.videoHeight;
          ctx.drawImage(video, 0, 0);
          const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
          const code = jsQR(imageData.data, imageData.width, imageData.height);
          if (code) {
            closeScanner();
            parseReceiptQR(code.data);
            return;
          }
        }
        animFrameId = requestAnimationFrame(scan);
      };

      animFrameId = requestAnimationFrame(scan);
    } catch (e) {
      closeScanner();
      if (e.name === 'NotAllowedError' || e.name === 'PermissionDeniedError') {
        showToast('Немає доступу до камери');
      } else {
        showToast('Помилка камери: ' + e.message);
      }
    }
  })();
}

// ── Парсинг QR-коду чека ────────────────────────────────────
function parseReceiptQR(qrData) {
  try {
    const url = new URL(qrData);
    const params = url.searchParams;

    const sm = params.get('sm');
    const rawDate = params.get('date');

    let amount = sm ? parseFloat(sm) : null;
    let date = null;

    if (rawDate && rawDate.length === 8) {
      // YYYYMMDD → YYYY-MM-DD
      date = `${rawDate.slice(0, 4)}-${rawDate.slice(4, 6)}-${rawDate.slice(6, 8)}`;
    }

    if (amount && amount > 0) {
      openExpenseDialog({ amount, date, store: null, category: null });
    } else {
      showToast('QR не містить суму чека');
    }
  } catch (e) {
    showToast('QR не містить суму чека');
  }
}

// ── Відкриття діалогу витрати з пресетами ───────────────────
async function openExpenseDialog({ amount, store, date, category }) {
  const { openOperationDialog } = await import('./operations.js');
  openOperationDialog({
    type: 'Витрата',
    presetAmount: amount,
    presetDate: date || null,
    presetCategory: category || null,
    presetDesc: store || null,
  });
}
