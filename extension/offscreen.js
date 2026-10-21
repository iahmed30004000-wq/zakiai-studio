/* offscreen.js — بيجمّع قطع ملف النتيجة (base64) كـ Blob وبيرجّع رابط مؤقت للـ background عشان ينحفظ بالتنزيلات.
 * الـ service worker ما فيه URL.createObjectURL، فهالصفحة المخفية (offscreen) هي الحل المعتمد بـ MV3.
 * ما بيتصل بأي شبكة، وما بيقبل إلا رسائل الإضافة نفسها الموجّهة إله (target: "offscreen"). */
"use strict";

const PARTS = new Map();                       // id ← {chunks: Map(index ← Uint8Array), bytes}
const URLS = new Set();
const MAX_BYTES = 110 * 1024 * 1024;           // سقف الفيديو (100MB) + هامش
const STALE_MS = 10 * 60 * 1000;

function decode(b64) {
  const bin = atob(b64), bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

chrome.runtime.onMessage.addListener((m, sender, reply) => {
  if (!m || m.target !== "offscreen" || sender.id !== chrome.runtime.id) return false;
  if (m.type === "chunk") {
    if (typeof m.id !== "string" || !Number.isInteger(m.index) || m.index < 0 || typeof m.b64 !== "string") { reply({ ok: false }); return false; }
    let u = PARTS.get(m.id);
    if (!u) { u = { chunks: new Map(), bytes: 0 }; PARTS.set(m.id, u); setTimeout(() => PARTS.delete(m.id), STALE_MS); }
    const b = decode(m.b64);
    u.bytes += b.length;
    if (u.bytes > MAX_BYTES) { PARTS.delete(m.id); reply({ ok: false }); return false; }
    u.chunks.set(m.index, b);
    reply({ ok: true });
    return false;
  }
  if (m.type === "finish") {
    const u = PARTS.get(m.id);
    PARTS.delete(m.id);
    const total = Number(m.total);
    if (!u || !Number.isInteger(total) || total < 1 || u.chunks.size !== total) { reply({ ok: false, reason: "قطع الملف ناقصة" }); return false; }
    const parts = [];
    for (let i = 0; i < total; i++) { if (!u.chunks.has(i)) { reply({ ok: false, reason: "قطع الملف ناقصة" }); return false; } parts.push(u.chunks.get(i)); }
    const blob = new Blob(parts, { type: String(m.mime || "application/octet-stream") });
    const url = URL.createObjectURL(blob);
    URLS.add(url);
    reply({ ok: true, url, size: blob.size });
    return false;
  }
  if (m.type === "revoke") {
    if (URLS.delete(m.url)) URL.revokeObjectURL(m.url);
    reply({ ok: true });
    return false;
  }
  return false;
});
