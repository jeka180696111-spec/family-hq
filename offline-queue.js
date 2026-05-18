// ═══════════════════════════════════════════════════════════════
// OFFLINE QUEUE — IndexedDB-based queue for pending operations
// ═══════════════════════════════════════════════════════════════

const DB_NAME = 'budget-offline';
const DB_VERSION = 1;
const STORE = 'pending_ops';

function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = e => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: 'id', autoIncrement: true });
      }
    };
    req.onsuccess = e => resolve(e.target.result);
    req.onerror = e => reject(e.target.error);
  });
}

export async function queueOperation(op) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite');
    const store = tx.objectStore(STORE);
    const req = store.add({ ...op, queuedAt: new Date().toISOString() });
    req.onsuccess = () => resolve(req.result);
    req.onerror = e => reject(e.target.error);
  });
}

export async function flushQueue() {
  const db = await openDB();

  // Read all pending ops
  const ops = await new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readonly');
    const store = tx.objectStore(STORE);
    const req = store.getAll();
    req.onsuccess = () => resolve(req.result);
    req.onerror = e => reject(e.target.error);
  });

  if (!ops.length) return;

  // Import apiPost dynamically to avoid circular deps
  const { apiPost } = await import('./api.js');

  for (const op of ops) {
    try {
      const { id, queuedAt, ...body } = op;
      await apiPost(body);

      // Remove successfully synced op
      await new Promise((resolve, reject) => {
        const tx = db.transaction(STORE, 'readwrite');
        const store = tx.objectStore(STORE);
        const req = store.delete(id);
        req.onsuccess = () => resolve();
        req.onerror = e => reject(e.target.error);
      });
    } catch (e) {
      // Leave failed ops in queue for next flush
      console.warn('[offline-queue] flush failed for op', op.id, e.message);
    }
  }
}
