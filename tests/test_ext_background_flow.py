"""الـ service worker الحقيقي (background.js) + صفحة offscreen الحقيقية بـ node: chrome.* مزيّفة، والمحتوى (content.js) مُحاكى.

بيغطّي المسار الكامل للتجربة السريعة: رسالة النافذة ← تحقق ← فتح التبويب ← تشغيل المحرّك ← رفع قطع الملف ← تجميع Blob بالـ offscreen ←
chrome.downloads ← سجل «آخر التجارب»، ومسارات الوقوف والإلغاء. ما بيثبت إن كروم الحقيقي بيتصرف نفس الشي، بس بيمسك أخطاء المنطق
(متغيّر مش معرّف، ترتيب خاطئ، تنزيل رغم وقوف…).
"""

import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_ext_multisite import node, needs_node  # noqa: E402

HARNESS = r"""
const vm = require('vm'), fs = require('fs');
const read = (f) => fs.readFileSync(R + '/' + f, 'utf-8');

function build(opts) {
  opts = opts || {};
  const store = { ...(opts.store || {}) };
  const calls = { download: [], tabsCreate: [], tabsUpdate: [], offscreen: 0, notify: [], badge: [], sent: [], apiFetch: [] };
  const bgListeners = [], offListeners = [], removedListeners = [];
  let offscreenOpen = false, badge = '';

  // ── offscreen.js الحقيقي بسياقه الخاص ──
  const offCtx = vm.createContext({ atob, Blob, console, setTimeout, clearTimeout, URL: { createObjectURL: (b) => 'blob:chrome-extension://ext-id/' + b.size + '-' + Math.random().toString(36).slice(2, 6), revokeObjectURL: (u) => { calls.revoked = (calls.revoked || []).concat(u); } },
    chrome: { runtime: { id: 'ext-id', onMessage: { addListener: (f) => offListeners.push(f) } } } });
  vm.runInContext(read('offscreen.js'), offCtx);
  const toOffscreen = (m) => new Promise((resolve) => { let done = false; for (const f of offListeners) { const r = f(m, { id: 'ext-id' }, (x) => { done = true; resolve(x); }); } if (!offListeners.length) resolve(undefined); setTimeout(() => { if (!done) resolve(undefined); }, 50); });

  const chrome = {
    runtime: { id: 'ext-id', getManifest: () => ({ version: '0.3.0' }), getPlatformInfo: (cb) => cb && cb({}),
      onMessage: { addListener: (f) => bgListeners.push(f) }, onInstalled: { addListener() {} }, onStartup: { addListener() {} },
      getContexts: async () => (offscreenOpen ? [{ contextType: 'OFFSCREEN_DOCUMENT' }] : []),
      sendMessage: async (m) => { calls.sent.push(m.type); return toOffscreen(m); } },
    storage: { local: { get: async (keys) => { const out = {}; for (const k of [].concat(keys)) if (k in store) out[k] = JSON.parse(JSON.stringify(store[k])); return out; },
      set: async (o) => { Object.assign(store, JSON.parse(JSON.stringify(o))); }, remove: async (k) => { delete store[k]; } } },
    tabs: { create: async ({ url }) => { calls.tabsCreate.push(url); return { id: 7 }; }, get: async (id) => { if (opts.tabGone) throw new Error('no tab'); return { id }; },
      update: async (id, p) => { calls.tabsUpdate.push(p.url); return { id }; }, remove: async () => {},
      sendMessage: async (id, msg) => opts.content(msg, id, calls, bgListeners),
      onUpdated: { addListener: (f) => setTimeout(() => f(7, { status: 'complete' }), 0), removeListener() {} }, onRemoved: { addListener: (f) => removedListeners.push(f) } },
    action: { setBadgeText: async ({ text }) => { badge = text; calls.badge.push(text); }, getBadgeText: async () => badge },
    notifications: { create: (o) => calls.notify.push(o.title + ' | ' + o.message) },
    alarms: { get: async () => ({}), create() {}, onAlarm: { addListener() {} } },
    downloads: { download: async (o) => { calls.download.push(o); return 42; }, show() {} },
    offscreen: { createDocument: async () => { if (offscreenOpen) throw new Error('Only a single offscreen document may be created'); offscreenOpen = true; calls.offscreen++; } },
  };
  const ctx = vm.createContext({ chrome, console, setTimeout, setInterval, clearInterval, clearTimeout, atob, btoa, Blob, FormData, URL, Date, Math, JSON, Promise,
    fetch: async (u) => { calls.apiFetch.push(String(u)); throw new Error('no network in test'); } });
  ctx.self = ctx;
  ctx.importScripts = (...files) => files.forEach((f) => vm.runInContext(read(f), ctx));
  vm.runInContext(read('background.js'), ctx);
  const send = (msg) => new Promise((resolve) => { const f = bgListeners.find((g) => g.length); let async_ = false; const r = bgListeners[0](msg, { tab: { id: 7 } }, (x) => resolve(x)); if (r !== true) setTimeout(() => resolve(undefined), 20); });
  const waitFor = async (pred, ms) => { const t0 = Date.now(); while (Date.now() - t0 < (ms || 4000)) { if (await pred()) return true; await new Promise((r) => setTimeout(r, 15)); } return false; };
  return { store, calls, send, waitFor, removedListeners, chrome };
}

// المحتوى المحاكى: بيرفع ملف النتيجة قطعتين ويرد بنجاح، أو بيرد بوقوف
const B64 = (s) => Buffer.from(s).toString('base64');
const okContent = (type, mime) => async (msg, id, calls, bg) => {
  if (msg.type !== 'run') return { stop: false };
  calls.runMsg = { kind: msg.kind, siteKey: msg.siteKey, dest: msg.dest, task: msg.task, refs: msg.refs.length, mode: msg.mode, url: msg.kcfg.url };
  const upId = 'u' + Math.random().toString(36).slice(2, 7), parts = ['AAAA', 'BBBB'];
  for (let i = 0; i < parts.length; i++) {
    const ack = await new Promise((res) => bg[0]({ type: 'chunk', id: upId, index: i, total: parts.length, b64: B64(parts[i]), dest: msg.dest }, { tab: { id } }, res));
    if (!ack || !ack.ok) return { stop: true, code: 'download_failed', reason: 'رفض القطعة ' + i };
  }
  return { ok: true, uploadId: upId, mime, size: 8, total: parts.length, w: 1000, h: 1000 };
};
const stopContent = (code, reason, diag) => async (msg) => (msg.type === 'run' ? { stop: true, code, reason, step: 'step3:click', diag } : { stop: false });
const quick = (o) => ({ type: 'quick', site: 'flow', kind: 'image', prompt: 'زجاجة عطر', aspect: '9:16', mode: 'max', refs: [], ...(o || {}) });
"""


def run_h(body: str):
    """التنزيل بيحط مؤقّت 120ث لتحرير رابط الـ blob (بالـ service worker الحقيقي مفيد، بـ node بيمنع الخروج): بنطلع بعد الطباعة."""
    return node(HARNESS + body + "\nsetTimeout(() => process.exit(0), 5);")


@needs_node
def test_quick_run_success_saves_the_file_under_videopattern_folder_and_logs_history():
    o = run_h("""
const h = build({ content: okContent('image', 'image/png') });
const r = await h.send(quick());
const done = await h.waitFor(async () => { const hist = (await h.chrome.storage.local.get(['history'])).history || []; return hist[0] && hist[0].status !== 'running'; });
const hist = h.store.history;
out({ r: { ok: r.ok, id: /^quick-\\d{4}-\\d\\d-\\d\\d-\\d\\d-\\d\\d-\\d\\d$/.test(r.id) }, done, hist, run: h.calls.runMsg, dl: h.calls.download, offscreen: h.calls.offscreen, sent: h.calls.sent,
      tabs: h.calls.tabsCreate, badge: h.calls.badge, notify: h.calls.notify, hold: h.store.hold })
""")
    assert o["r"] == {"ok": True, "id": True} and o["done"] is True
    row = o["hist"][0]
    assert row["status"] == "done" and row["site"] == "flow" and row["kind"] == "image" and row["prompt"] == "زجاجة عطر" and row["size"] == 8 and row["downloadId"] == 42
    assert re.fullmatch(r"Zakiai/flow/\d{4}-\d\d-\d\d-\d\d-\d\d-\d\d\.png", row["file"])
    assert len(o["dl"]) == 1 and o["dl"][0]["filename"] == row["file"] and o["dl"][0]["url"].startswith("blob:chrome-extension://ext-id/")
    assert o["dl"][0]["conflictAction"] == "uniquify" and o["dl"][0]["saveAs"] is False
    assert o["run"]["dest"] == "download" and o["run"]["siteKey"] == "flow" and o["run"]["kind"] == "image" and o["run"]["mode"] == "max"
    assert o["run"]["task"]["aspect"] == "9:16" and o["run"]["task"]["prompt"] == "زجاجة عطر" and o["run"]["url"] == "https://flow.google.com/"
    assert o["offscreen"] == 1 and o["sent"].count("chunk") == 2 and o["sent"].count("finish") == 1 and o["tabs"] == ["https://flow.google.com/"]
    assert o["hold"] is False and o["badge"][-1] == "" and any("خلصت التجربة" in n for n in o["notify"])


import re  # noqa: E402


@needs_node
def test_quick_run_stop_never_downloads_keeps_the_diag_and_sets_hold():
    o = run_h("""
const diag = { host: 'flow.google.com', buttons: [{ t: 'button', aria: 'Start generation' }] };
const h = build({ content: stopContent('unknown_page', 'ما لقيت العنصر المطلوب', diag), store: { token: 'tok', studioUrl: 'http://localhost:8000', script: 's1.json' } });
const r = await h.send(quick());
await h.waitFor(async () => { const hist = h.store.history || []; return hist[0] && hist[0].status !== 'running'; });
out({ r, row: h.store.history[0], dl: h.calls.download.length, hold: h.store.hold, badge: h.calls.badge[h.calls.badge.length - 1], notify: h.calls.notify,
      fetched: h.calls.apiFetch.filter(u => u.includes('/api/ext/diag')).length, stopCalls: h.calls.apiFetch.filter(u => u.includes('/ext/stop')).length })
""")
    row = o["row"]
    assert o["r"]["ok"] is True and row["status"] == "stopped" and row["code"] == "unknown_page" and "ما لقيت" in row["reason"] and row["step"] == "step3:click"
    assert o["dl"] == 0 and o["hold"] is True and o["badge"] == "!" and any("وقفت التجربة" in n for n in o["notify"])
    assert o["fetched"] == 1                         # تقرير diag انبعت للاستوديو (فيه توكن)
    assert o["stopCalls"] == 0                       # التجربة السريعة ما بتلمس تحكم سيناريو بالاستوديو


@needs_node
def test_quick_run_validation_errors_come_back_immediately_and_start_nothing():
    o = run_h("""
const h = build({ content: okContent('image', 'image/png') });
const bad = {
  empty: await h.send(quick({ prompt: '   ' })), long: await h.send(quick({ prompt: 'x'.repeat(4001) })),
  wrongKind: await h.send(quick({ site: 'chatgpt', kind: 'music' })), noSite: await h.send(quick({ site: 'bing' })),
  bigRefs: await h.send(quick({ refs: [{ name: 'a', mime: 'image/png', b64: 'A'.repeat(60 * 1024 * 1024) }] })),
};
const histAfter = h.store.history || [];
// مراجع: أول 4 بس بتتاخد وغير الصور بتنشال (هون 3 صور)، والنسبة والسرعة غير المعروفة ← الافتراضي
const h2 = build({ content: okContent('image', 'image/png') });
await h2.send(quick({ aspect: '7:3', mode: 'turbo', refs: [{ name: 'a.png', mime: 'image/png', b64: 'AA==' }, { name: 'x.exe', mime: 'application/x-msdownload', b64: 'AA==' }, ...[1, 2, 3, 4].map(i => ({ name: 'r' + i, mime: 'image/jpeg', b64: 'AA==' }))] }));
await h2.waitFor(async () => (h2.store.history || [])[0] && h2.store.history[0].status !== 'running');
out({ bad, histAfter, tabs: h.calls.tabsCreate.length, run2: h2.calls.runMsg })
""")
    for k, r in o["bad"].items():
        assert r["ok"] is False and r["reason"], k
    assert "اكتب البرومبت" in o["bad"]["empty"]["reason"] and "طويل" in o["bad"]["long"]["reason"] and "ما بيدعم" in o["bad"]["wrongKind"]["reason"]
    assert "كبيرة" in o["bad"]["bigRefs"]["reason"]
    assert o["histAfter"] == [] and o["tabs"] == 0
    assert o["run2"]["refs"] == 3 and o["run2"]["task"]["aspect"] == "9:16" and o["run2"]["mode"] == "natural"


@needs_node
def test_quick_run_blocks_a_second_run_while_one_is_running_and_cancel_aborts():
    o = run_h("""
let release; const gate = new Promise((r) => { release = r; });
const aborts = [];
const content = async (msg) => { if (msg.type === 'abort') { aborts.push(1); release(); return { ok: true }; }
  if (msg.type === 'run') { await gate; return { stop: true, code: 'cancelled', reason: 'المالك ألغى التشغيل', step: 'generating' }; } return {}; };
const h = build({ content });
const first = await h.send(quick());
await h.waitFor(async () => h.calls.tabsCreate.length === 1);
const second = await h.send(quick({ prompt: 'تانية' }));
const cancel = await h.send({ type: 'quick_cancel' });
await h.waitFor(async () => (h.store.history || [])[0] && h.store.history[0].status !== 'running');
out({ first: first.ok, second, cancel, aborts: aborts.length, row: h.store.history[0], count: h.store.history.length, dl: h.calls.download.length, hold: h.store.hold, badge: h.calls.badge.at(-1) })
""")
    assert o["first"] is True and o["second"]["ok"] is False and "استنى" in o["second"]["reason"]
    assert o["cancel"]["ok"] is True and o["aborts"] == 1
    assert o["row"]["status"] == "cancelled" and o["count"] == 1 and o["dl"] == 0 and o["hold"] is False       # إلغاء ≠ وقوف: ما في hold


@needs_node
def test_quick_run_download_failure_and_history_limits():
    o = run_h("""
// 1) تنزيل فاشل ← سجل «فشلت» + الشارة «!»
const h = build({ content: okContent('audio', 'audio/mpeg') });
h.chrome.downloads.download = async () => { throw new Error('Invalid filename'); };
await h.send(quick({ site: 'flowmusic', kind: 'music' }));
await h.waitFor(async () => (h.store.history || [])[0] && h.store.history[0].status !== 'running');
const failed = h.store.history[0];
// 2) السجل 20 بالكتير ويتمسح
const g = build({ content: okContent('image', 'image/png'), store: { history: Array.from({ length: 25 }, (_, i) => ({ id: 'old' + i, at: i, site: 'flow', kind: 'image', prompt: 'p', status: 'done' })) } });
await g.send(quick());
await g.waitFor(async () => (g.store.history || [])[0] && g.store.history[0].status !== 'running');
const n = g.store.history.length, newest = g.store.history[0].id.startsWith('quick-'); const cleared = await g.send({ type: 'clear_history' });
out({ failed, badge: h.calls.badge.at(-1), n, newest, cleared, after: g.store.history })
""")
    assert o["failed"]["status"] == "error" and "Invalid filename" in o["failed"]["reason"] and o["badge"] == "!"
    assert o["n"] == 20 and o["newest"] is True and o["cleared"]["ok"] is True and o["after"] == []


@needs_node
def test_chunk_forwarding_validation_and_offscreen_rejects_foreign_messages():
    o = run_h("""
const h = build({ content: okContent('image', 'image/png') });
const ok = await new Promise((res) => h.chrome.runtime.sendMessage({ target: 'offscreen', type: 'chunk', id: 'a', index: 0, b64: B64('xy') }).then(res));
const badShape = await h.chrome.runtime.sendMessage({ target: 'offscreen', type: 'chunk', id: 7, index: 'x', b64: 1 });
const missing = await h.chrome.runtime.sendMessage({ target: 'offscreen', type: 'finish', id: 'a', total: 2, mime: 'image/png' });     // قطعة ناقصة
await h.chrome.runtime.sendMessage({ target: 'offscreen', type: 'chunk', id: 'b', index: 0, b64: B64('xy') });
const fin = await h.chrome.runtime.sendMessage({ target: 'offscreen', type: 'finish', id: 'b', total: 1, mime: 'audio/mpeg' });
const again = await h.chrome.runtime.sendMessage({ target: 'offscreen', type: 'finish', id: 'b', total: 1, mime: 'audio/mpeg' });        // خلص مرة، ما بيتكرر
const revoked = await h.chrome.runtime.sendMessage({ target: 'offscreen', type: 'revoke', url: fin.url });
const notTarget = await h.chrome.runtime.sendMessage({ type: 'chunk', id: 'c', index: 0, b64: B64('xy') });                             // مش موجّهة للـ offscreen: بيتجاهلها
// الـ background: chunk عادي (بلا dest) ما بيروح للـ offscreen
const before = h.calls.sent.length;
const plain = await new Promise((res) => h.send({ type: 'chunk', id: 'p', index: 0, total: 1, b64: B64('xy') }).then(res));
out({ ok, badShape, missing, fin: { ok: fin.ok, size: fin.size, blob: fin.url.startsWith('blob:') }, again, revoked, notTarget: String(notTarget), plain, forwarded: h.calls.sent.length - before })
""")
    assert o["ok"] == {"ok": True} and o["badShape"] == {"ok": False} and o["missing"]["ok"] is False and "ناقصة" in o["missing"]["reason"]
    assert o["fin"] == {"ok": True, "size": 2, "blob": True} and o["again"]["ok"] is False and o["revoked"] == {"ok": True}
    assert o["notTarget"] == "undefined"                             # ما حدا ردّ (target مش offscreen)
    assert o["plain"] == {"ok": True} and o["forwarded"] == 0        # وضع الاستوديو القديم بيضل بذاكرة الـ background


@needs_node
def test_studio_mode_still_uploads_through_the_background_not_the_downloads():
    o = run_h("""
const h = build({ content: okContent('image', 'image/png') });
const up = await h.send({ type: 'chunk', id: 'u1', index: 0, total: 1, b64: B64('hello') });
out({ up, dl: h.calls.download.length, offscreen: h.calls.offscreen })
""")
    assert o["up"] == {"ok": True} and o["dl"] == 0 and o["offscreen"] == 0


@needs_node
def test_a_pinned_flow_project_url_is_used_only_when_it_matches_the_strict_pattern():
    o = run_h("""
const GOOD = 'https://flow.google.com/project/789394ac-26de-4c2d-8a2b-e382bfbab732';
const run = async (store, site, kind) => { const h = build({ content: okContent('image', 'image/png'), store });
  await h.send(quick({ site: site || 'flow', kind: kind || 'image' })); await h.waitFor(async () => (h.store.history || [])[0] && h.store.history[0].status !== 'running'); return h.calls.tabsCreate[0]; };
out({ pinned: await run({ flowProject: GOOD }), slash: await run({ flowProject: GOOD + '/' }), none: await run({}), evil: await run({ flowProject: 'https://evil.example/project/789394ac-26de-4c2d-8a2b-e382bfbab732' }),
      short: await run({ flowProject: 'https://flow.google.com/project/123' }), http: await run({ flowProject: GOOD.replace('https', 'http') }), other: await run({ flowProject: GOOD }, 'gemini') })
""")
    good = "https://flow.google.com/project/789394ac-26de-4c2d-8a2b-e382bfbab732"
    assert o["pinned"] == good and o["slash"] == good + "/"
    assert o["none"] == o["evil"] == o["short"] == o["http"] == "https://flow.google.com/"
    assert o["other"] == "https://gemini.google.com/app"                  # التثبيت لـ Flow بس


@needs_node
def test_open_site_only_opens_the_page_in_the_single_tab_without_any_generation():
    o = run_h("""
const h = build({ content: okContent('image', 'image/png') });
const first = await h.send({ type: 'open_site', site: 'flow', kind: 'image' });
const created = h.calls.tabsCreate.slice();
h.store.tabId = 7;                                              // التبويب انحفظ بأول فتح
const second = await h.send({ type: 'open_site', site: 'flowmusic', kind: 'music' });
const bad = await h.send({ type: 'open_site', site: 'chatgpt', kind: 'music' });
const nosite = await h.send({ type: 'open_site', site: 'bing', kind: 'image' });
const g = build({ content: okContent('image', 'image/png') });
await g.send(quick());                                          // تشغيل شغّال ← فتح الموقع مرفوض
const busy = await g.send({ type: 'open_site', site: 'flow', kind: 'image' });
out({ first, created, second, updates: h.calls.tabsUpdate, bad, nosite, busy, history: h.store.history || null, runMsg: h.calls.runMsg || null, downloads: h.calls.download.length })
""")
    assert o["first"] == {"ok": True} and o["created"] == ["https://flow.google.com/"]
    assert o["second"] == {"ok": True} and o["updates"] == ["https://www.flowmusic.app/"]          # نفس التبويب (ما انفتح تاني)
    assert o["bad"]["ok"] is False and "ما بيدعم" in o["bad"]["reason"] and o["nosite"]["ok"] is False
    assert o["busy"]["ok"] is False and "استنى" in o["busy"]["reason"]
    assert o["history"] is None and o["runMsg"] is None and o["downloads"] == 0                       # ما في توليد ولا سجل
