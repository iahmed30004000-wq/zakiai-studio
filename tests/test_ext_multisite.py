"""إضافة المتصفح متعددة المواقع (عقد ext_contract.md — جانب الإضافة): اختبارات node صافية + ساكنة.

ما فيها أي اتصال بخادم ولا بمواقع حقيقية: المحدّدات الافتراضية تخمينية وغير مجرّبة، فالاختبارات بتفحص
المنطق (دمج الإعداد، اختيار الموقع، القوالب، المحرّك بصفحة وهمية، قيود الأمان) مش نجاح الموقع الحقيقي.
"""

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "extension"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node غير متوفر")

PRELUDE = """
const R = __EXT__;
const A = require(R + '/lib/adapters.js');
const E = require(R + '/lib/engine.js');
const P = require(R + '/lib/pace.js');
const D = require(R + '/lib/detect.js');
const DEF = A.mergeConfig(A.DEFAULT_CONFIG, null).config;
const out = (x) => console.log(JSON.stringify(x));
"""


def node(body: str):
    src = PRELUDE.replace("__EXT__", json.dumps(EXT.as_posix())) + \
        "\n(async () => {\n" + body + "\n})().catch(e => { console.error((e && e.stack) || e); process.exit(1); });\n"
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "t.js"
        f.write_text(src, encoding="utf-8")
        r = subprocess.run([NODE, str(f)], capture_output=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def read(name: str) -> str:
    return (EXT / name).read_text(encoding="utf-8")


# ───────────────────────── الإعداد الافتراضي ─────────────────────────
@needs_node
def test_default_config_covers_the_six_sites_with_contract_kinds_and_is_unverified():
    o = node("out({sites: Object.keys(DEF.sites), kinds: Object.fromEntries(Object.entries(DEF.sites).map(([k, s]) => [k, Object.keys(s.kinds)])),"
             " verified: Object.values(DEF.sites).map(s => s.verified), warn: A.mergeConfig(A.DEFAULT_CONFIG, null).warnings})")
    assert o["sites"] == ["gemini", "chatgpt", "aistudio", "flow", "flowmusic", "elevenlabs"]
    k = o["kinds"]
    assert set(k["elevenlabs"]) == {"voice", "ahat"} and k["chatgpt"] == ["image"] and k["gemini"] == ["image"]
    assert k["aistudio"] == ["image"] and set(k["flow"]) == {"video", "image"} and k["flowmusic"] == ["music"]
    assert o["verified"] == [False] * 6                      # ما انجرّبت على المواقع الحقيقية
    assert o["warn"] == []                                   # الافتراضي نفسه لازم يعدّي التنظيف بلا تحذيرات


def test_adapters_header_states_selectors_are_guesses_not_tested_on_real_sites():
    head = read("lib/adapters.js")[:2500]
    assert "تخمينية" in head and "ما انجرّبت" in head


# ───────────────────────── اختيار الموقع / توافق الأنواع ─────────────────────────
@needs_node
def test_site_selection_by_host_and_kind_compatibility():
    o = node("""
const h = (x) => A.siteForHost(x, DEF);
out({hosts: ['gemini.google.com','chatgpt.com','aistudio.google.com','flow.google.com','elevenlabs.io','flowmusic.app','www.flowmusic.app'].map(h),
     bad: ['evil.example.com','google.com','www.chatgpt.com','labs.google','', null].map(h),
     voice: A.sitesForKind(DEF,'voice').map(s=>s.key), ahat: A.sitesForKind(DEF,'ahat').map(s=>s.key),
     image: A.sitesForKind(DEF,'image').map(s=>s.key), video: A.sitesForKind(DEF,'video').map(s=>s.key), music: A.sitesForKind(DEF,'music').map(s=>s.key),
     kindsOfFlow: A.kindsOf(DEF,'flow'), kindsOfNone: A.kindsOf(DEF,'bing'),
     pick: [A.pickSite(DEF,'image',['flow']), A.pickSite(DEF,'image',['elevenlabs']), A.pickSite(DEF,'image',[]), A.pickSite(DEF,'music',['gemini']), A.pickSite(DEF,'voice',[null,'elevenlabs'])],
     flags: A.sitesForKind(DEF,'music')[0]})
""")
    assert o["hosts"] == ["gemini", "chatgpt", "aistudio", "flow", "elevenlabs", "flowmusic", "flowmusic"]
    assert o["bad"] == [None] * 6                                  # labs.google (عنوان Flow القديم) مش مسموح هلأ
    assert o["voice"] == ["elevenlabs"] and o["ahat"] == ["elevenlabs"] and o["music"] == ["flowmusic"]
    assert o["image"] == ["gemini", "chatgpt", "aistudio", "flow"] and o["video"] == ["flow"]
    assert o["kindsOfFlow"] == ["image", "video"] and o["kindsOfNone"] == []
    assert o["pick"] == ["flow", "gemini", "gemini", "flowmusic", "elevenlabs"]       # مفضّل يدعم النوع، وإلا أول موقع يدعمه
    assert o["flags"]["verified"] is False


# ───────────────────────── تفكيك steps وقوالبها ─────────────────────────
@needs_node
def test_parse_steps_validates_and_normalises():
    o = node("""
const ok = A.parseSteps(DEF.sites.flow.kinds.video);
const bad = [
  {steps: []}, {}, {steps: [{do: 'fly', sel: ['a']}]}, {steps: [{do: 'click', sel: []}]}, {steps: [{do: 'click'}]},
  {steps: [{do: 'type', sel: ['input[type=password]'], text: 'x'}]}, {steps: [{do: 'click', sel: ['#a', 7]}]},
  {steps: [{do: 'wait', ms: -1}]}, {steps: [{do: 'wait', ms: 'x'}]}, {steps: [{do: 'wait', ms: 999999}]},
].map(k => A.parseSteps(k).errors.length > 0);
const w = A.parseSteps({steps: [{do: 'wait', ms: 1500}, {do: 'type', sel: ['#a']}, {do: 'click', sel: ['#b'], optional: true}]});
out({ok, bad, w: w.steps})
""")
    ok = o["ok"]["steps"]
    assert o["ok"]["errors"] == [] and [s["do"] for s in ok if s["do"] != "click"] == ["attach", "type"]
    assert ok[-1]["do"] == "click" and ok[-1]["optional"] is False and ok[-1]["sel"] == ['button[aria-label="Start generation"]']
    typ = next(s for s in ok if s["do"] == "type")
    assert typ["text"] == "{prompt}" and typ["sel"][0] == 'div.ProseMirror[role="textbox"]'
    assert any(s.get("if") == "pressed" for s in ok) and any(s.get("needs") == "refs" for s in ok) and any(s.get("waitMs") for s in ok)
    assert all(o["bad"]), o["bad"]
    assert o["w"] == [{"do": "wait", "ms": 1500}, {"do": "type", "sel": ["#a"], "optional": False, "text": "{prompt}"},
                      {"do": "click", "sel": ["#b"], "optional": True}]


@needs_node
def test_templates_fill_prompt_and_seconds_in_one_pass():
    o = node("""
out([A.applyTemplate('{prompt}', {prompt: 'قطة تركض'}),
     A.applyTemplate('{prompt} — {seconds}s', {prompt: 'x', seconds: 3.4}),
     A.applyTemplate('{seconds}', {seconds: 3}), A.applyTemplate('{seconds}|', {}), A.applyTemplate('{seconds}|', {seconds: -1}),
     A.applyTemplate('{prompt}', {prompt: 'داخل {seconds} نص', seconds: 9}),     // القيمة المحقونة ما بتتوسّع
     A.applyTemplate('{other} {prompt}', {prompt: 'p'}), A.applyTemplate(null, {}), A.applyTemplate('a{prompt}b{prompt}', {prompt: '1'}),
     A.applyTemplate('{seconds}', {seconds: 2.04}), A.applyTemplate('{prompt}', {})])
""")
    assert o == ["قطة تركض", "x — 3.4s", "3", "|", "|", "داخل {seconds} نص", "{other} p", "", "a1b1", "2", ""]


@needs_node
def test_timeouts_by_kind_default_and_config_override_with_clamps():
    o = node("""
const t = (k, c) => A.timeoutFor(k, c);
out({voice: t('voice', {}), ahat: t('ahat', {}), image: t('image', {}), music: t('music', {}), video: t('video', {}),
     cfg: t('video', {timeoutSec: 1200}), low: t('image', {timeoutSec: 1}), high: t('image', {timeoutSec: 99999}), junk: t('music', {timeoutSec: 'x'}),
     fromDefaults: [DEF.sites.elevenlabs.kinds.voice.timeoutSec, DEF.sites.flow.kinds.video.timeoutSec, DEF.sites.flowmusic.kinds.music.timeoutSec]})
""")
    assert (o["voice"], o["image"], o["music"], o["video"]) == (180, 300, 300, 900)
    assert o["cfg"] == 1200 and o["low"] == 30 and o["high"] == 3600 and o["junk"] == 300
    assert o["fromDefaults"] == [180, 900, 300]


# ───────────────────────── مطابقة نوع النتيجة ─────────────────────────
@needs_node
def test_result_type_matching_newness_and_choice():
    o = node("""
const img = (w, h, extra) => ({tag: 'IMG', w, h, complete: true, src: 'https://x/' + w, ...extra});
out({
  image: [A.matchesResult('image', img(512, 512)), A.matchesResult('image', img(200, 900)), A.matchesResult('image', img(512, 512, {complete: false})),
          A.matchesResult('image', {tag: 'VIDEO', w: 999, h: 999}), A.matchesResult('image', {tag: 'AUDIO'})],
  audio: [A.matchesResult('audio', {tag: 'AUDIO'}), A.matchesResult('audio', {tag: 'SOURCE', parentTag: 'AUDIO'}), A.matchesResult('audio', {tag: 'SOURCE', parentTag: 'VIDEO'}), A.matchesResult('audio', {tag: 'VIDEO'})],
  video: [A.matchesResult('video', {tag: 'VIDEO'}), A.matchesResult('video', {tag: 'SOURCE', parentTag: 'VIDEO'}), A.matchesResult('video', {tag: 'IMG', w: 999, h: 999}), A.matchesResult('video', {tag: 'SOURCE', parentTag: 'AUDIO'})],
  unknownType: A.matchesResult('pdf', {tag: 'IMG'}),
  isNew: [A.isNewResult({src: 'a'}, new Set(['a']), false), A.isNewResult({src: 'b'}, new Set(['a']), false), A.isNewResult({src: 'b'}, new Set(), true), A.isNewResult({src: ''}, new Set(['']), false)],
  pick: [A.pickResult('image', [img(300, 300), img(900, 600), img(500, 500)]), A.pickResult('image', [img(400, 400), img(400, 400)]),
         A.pickResult('audio', [{}, {}, {}]), A.pickResult('video', [{}]), A.pickResult('video', []), A.pickResult('image', [])],
  mime: [A.mimeOk('image', 'image/png'), A.mimeOk('image', 'audio/mpeg'), A.mimeOk('audio', 'audio/mpeg; codecs=x'), A.mimeOk('video', ''), A.mimeOk('video', 'application/octet-stream'), A.mimeOk('video', 'text/html')],
  ext: [A.extFor('image/png', 'image'), A.extFor('audio/mpeg', 'audio'), A.extFor('video/webm', 'video'), A.extFor('', 'video'), A.extFor('x/y', 'audio')],
})
""")
    assert o["image"] == [True, False, False, False, False]
    assert o["audio"] == [True, True, False, False] and o["video"] == [True, True, False, False]
    assert o["unknownType"] is False
    assert o["isNew"] == [False, True, False, True]          # مصدر فاضي ما بينقارن بالـ src (بيعتمد على «شفناه قبل»)
    assert o["pick"] == [1, 1, 2, 0, -1, -1]
    assert o["mime"] == [True, False, True, True, True, False]
    assert o["ext"] == ["png", "mp3", "webm", "mp4", "mp3"]


# ───────────────────────── دمج الإعداد ─────────────────────────
@needs_node
def test_remote_config_overrides_defaults_deeply_and_keeps_the_rest():
    o = node("""
const remote = {version: 7, sites: {flow: {verified: true, adapter_version: 4,
   kinds: {video: {steps: [{do: 'type', sel: ['#p'], text: '{prompt} ({seconds}s)'}, {do: 'click', sel: ['#go']}], busy: ['.spin'], timeoutSec: 1000}},
   selftest: {composer: ['#p']}}}};
const m = A.mergeConfig(A.DEFAULT_CONFIG, remote);
const f = m.config.sites.flow;
out({version: m.config.version, warnings: m.warnings, verified: f.verified, av: f.adapter_version,
     steps: f.kinds.video.steps.map(s => s.do), sel: f.kinds.video.steps[0].sel, busy: f.kinds.video.busy, timeout: f.kinds.video.timeoutSec,
     resultKept: f.kinds.video.result.sel, imageKept: !!f.kinds.image, selftest: f.selftest,
     gemini: m.config.sites.gemini.verified, geminiSame: JSON.stringify(m.config.sites.gemini) === JSON.stringify(DEF.sites.gemini)})
""")
    assert o["version"] == 7 and o["warnings"] == [] and o["verified"] is True and o["av"] == 4
    assert o["steps"] == ["type", "click"] and o["sel"] == ["#p"]                 # المصفوفات بتتبدّل كاملة (مش بتندمج)
    assert o["busy"] == [".spin"] and o["timeout"] == 1000
    assert o["resultKept"] == ["video[src]", "video source", "video"] and o["imageKept"] is True  # اللي ما انبعت بيضل من الافتراضي
    assert o["selftest"] == {"composer": ["#p"]} and o["gemini"] is False and o["geminiSame"] is True


@needs_node
def test_merge_with_missing_or_broken_remote_falls_back_to_defaults_or_stored():
    o = node("""
const same = (c) => JSON.stringify(c) === JSON.stringify(DEF);
const stored = A.mergeConfig(A.DEFAULT_CONFIG, {version: 5, sites: {gemini: {kinds: {image: {steps: [{do: 'click', sel: ['#stored']}]}}}}}).config;
// الخادم مش متاح ← remote فاضي ← نكمّل على المخزّن (بنستخدمه كأساس)
const offline = A.mergeConfig(stored, null).config;
// مخزّن + تحديث جزئي جديد
const upd = A.mergeConfig(stored, {version: 6, sites: {chatgpt: {label: 'ChatGPT 2'}}}).config;
out({nullRemote: same(A.mergeConfig(A.DEFAULT_CONFIG, null).config), garbage: [same(A.mergeConfig(A.DEFAULT_CONFIG, 'x').config), same(A.mergeConfig(A.DEFAULT_CONFIG, []).config), same(A.mergeConfig(A.DEFAULT_CONFIG, {sites: 5}).config)],
     storedKept: offline.sites.gemini.kinds.image.steps[0].sel, offVersion: offline.version,
     updKeepsStoredSel: upd.sites.gemini.kinds.image.steps[0].sel, updLabel: upd.sites.chatgpt.label, updVersion: upd.version,
     baseUntouched: A.DEFAULT_CONFIG.sites.gemini.kinds.image.steps[0].do})
""")
    assert o["nullRemote"] is True and o["garbage"] == [True, True, True]
    assert o["storedKept"] == ["#stored"] and o["offVersion"] == 5
    assert o["updKeepsStoredSel"] == ["#stored"] and o["updLabel"] == "ChatGPT 2" and o["updVersion"] == 6
    assert o["baseUntouched"] == "attach"                                             # الدمج ما بيعدّل الأساس


@needs_node
def test_merge_rejects_unsafe_or_malformed_remote_pieces_with_warnings():
    o = node("""
const remote = {sites: {
  evil: {hosts: ['evil.example.com'], newUrl: 'https://evil.example.com/', kinds: {image: {steps: [{do: 'click', sel: ['a']}], result: {type: 'image', sel: ['img']}}}},
  gemini: {hosts: ['gemini.google.com', 'evil.example.com'], newUrl: 'https://evil.example.com/x',
           kinds: {image: {url: 'https://evil.example.com/app', steps: [{do: 'click', sel: ['a']}], result: {type: 'image', sel: ['img']}}}},
  chatgpt: {kinds: {image: {steps: [{do: 'type', sel: ['input[type=password]'], text: 'x'}, {do: 'click', sel: ['#b']}]}}},
  aistudio: {kinds: {image: {result: {type: 'audio', sel: ['audio']}}}},
  flowmusic: {kinds: {music: {url: 'http://flowmusic.app/', steps: [{do: 'click', sel: ['#b']}]}, bogus: {steps: []}}},
  elevenlabs: {kinds: {voice: {result: {type: 'audio', sel: ['audio[src]', 'input[type="password"]']}}}, selftest: {composer: ['#pw[type=password]']}},
  flow: {hosts: ['evil.example.com'], verified: 'yes'},
}};
const m = A.mergeConfig(A.DEFAULT_CONFIG, remote);
const c = m.config;
out({sites: Object.keys(c.sites), warnings: m.warnings.length,
     geminiHosts: c.sites.gemini.hosts, geminiNew: c.sites.gemini.newUrl, geminiImageUrl: c.sites.gemini.kinds.image.url,
     chatgptSteps: c.sites.chatgpt.kinds.image.steps.map(s => s.do), aistudioType: c.sites.aistudio.kinds.image.result.type,
     musicUrl: c.sites.flowmusic.kinds.music.url, musicKinds: Object.keys(c.sites.flowmusic.kinds),
     voiceResult: c.sites.elevenlabs.kinds.voice.result.sel, elSelftest: c.sites.elevenlabs.selftest,
     flowHosts: c.sites.flow.hosts, flowVerified: c.sites.flow.verified,
     allHosts: [...new Set(Object.values(c.sites).flatMap(s => s.hosts))].sort(),
     urlsOk: Object.values(c.sites).every(s => [s.newUrl, ...Object.values(s.kinds).map(k => k.url)].every(u => A.ALLOWED_HOSTS.includes(new URL(u).hostname) && u.startsWith('https://')))})
""")
    assert "evil" not in o["sites"] and len(o["sites"]) == 6 and o["warnings"] >= 6
    assert o["geminiHosts"] == ["gemini.google.com"] and o["geminiNew"] == "https://gemini.google.com/app"
    assert o["geminiImageUrl"] == "https://gemini.google.com/app"              # رابط خارج النطاق ← الافتراضي
    assert o["chatgptSteps"] == ["attach", "type", "click"]                     # خطوة بمحدّد كلمة سر ← النوع كله يرجع للافتراضي
    assert o["aistudioType"] == "image"                                         # result.type لازم يطابق النوع
    assert o["musicUrl"] == "https://www.flowmusic.app/" and o["musicKinds"] == ["music"]
    assert o["voiceResult"] == ["audio[src]", "audio source"] and o["elSelftest"] == {"composer": ["textarea"]}
    assert o["flowHosts"] == ["flow.google.com"] and o["flowVerified"] is False  # verified لازم true حرفياً
    assert o["urlsOk"] is True and set(o["allHosts"]) <= {"gemini.google.com", "chatgpt.com", "aistudio.google.com", "flow.google.com", "elevenlabs.io", "flowmusic.app", "www.flowmusic.app"}


@needs_node
def test_null_in_remote_removes_a_kind_and_sensitive_selectors_are_detected():
    o = node("""
const m = A.mergeConfig(A.DEFAULT_CONFIG, {sites: {flow: {kinds: {image: null}}}}).config;
out({flowKinds: Object.keys(m.sites.flow.kinds), imageSites: A.sitesForKind(m, 'image').map(s => s.key),
     sens: ['input[type=password]', 'input[type="PASSWORD"]', '#otp', 'input[autocomplete=one-time-code]', 'textarea', 'button[aria-label*="Send" i]'].map(A.isSensitiveSelector)})
""")
    assert o["flowKinds"] == ["video"] and "flow" not in o["imageSites"]
    assert o["sens"] == [True, True, True, True, False, False]


# ───────────────────────── الفحص الذاتي والنسخة والتجزئة ─────────────────────────
@needs_node
def test_selftest_evaluation_chunk_plan_and_version_compare():
    o = node("""
const exists = (set) => (sels) => sels.some(s => set.has(s));
const CH = A.CHUNK_BYTES, size = 100 * 1024 * 1024;
const plan = A.chunkPlan(size), small = A.chunkPlan(10, 4);
out({
  st: [A.evalSelftest({composer: ['a', 'b']}, exists(new Set(['b']))), A.evalSelftest({composer: ['a'], send: ['z']}, exists(new Set(['a']))), A.evalSelftest({}, () => true), A.evalSelftest(null, () => true)],
  plan: {n: plan.length, last: plan[plan.length - 1], contiguous: plan.every((c, i) => c.index === i && (i === 0 || c.start === plan[i - 1].end)), total: plan[plan.length - 1].end, max: Math.max(...plan.map(c => c.end - c.start)), ch: CH},
  small, none: A.chunkPlan(0),
  allowed: [A.uploadAllowed(1), A.uploadAllowed(size), A.uploadAllowed(size + 1), A.uploadAllowed(0), A.uploadAllowed(NaN)],
  ver: [A.compareVersions('0.2.1', '0.2.0'), A.compareVersions('0.2.0', '0.2.0'), A.compareVersions('0.10.0', '0.9.9'), A.compareVersions('0.2', '0.2.0'), A.compareVersions('0.1.9', '0.2.0'), A.compareVersions(undefined, '0.0.1')],
})
""")
    assert o["st"] == [[], ["send"], ["no_selftest_selectors"], ["no_selftest_selectors"]]
    p = o["plan"]
    assert p["contiguous"] and p["total"] == 100 * 1024 * 1024 and p["n"] == 34 and p["max"] == p["ch"] <= 4 * 1024 * 1024
    assert o["small"] == [{"index": 0, "start": 0, "end": 4}, {"index": 1, "start": 4, "end": 8}, {"index": 2, "start": 8, "end": 10}] and o["none"] == []
    assert o["allowed"] == [True, True, False, False, False]
    assert o["ver"] == [1, 0, 1, 0, -1, -1]


# ───────────────────────── المحرّك بصفحة وهمية ─────────────────────────
FAKE = """
Math.random = () => 0.5;                                          // انتظار ثابت: عدد الفحوصات لازم يتطابق بين التشغيلين
function page(o) {
  o = o || {};
  const st = { t: 0, n: 0, ev: [], fetched: 0, abort: false, ...o };
  st.present = new Set(o.present || ['input[type="file"]', 'textarea', 'button[aria-label*="Generate" i]', 'audio[src]', 'video[src]', '#prompt-textarea', 'button[data-testid=send-button]']);
  st.disabled = new Set(o.disabled || []); st.sensitive = new Set(o.sensitive || []);
  st.results = (o.results || []).map((r, i) => ({ id: 'old' + i, appearAt: -1, ...r }));
  st.clickAt = o.clickAt || {};                                  // sel ← دالة بتنفَّذ عند الضغط (بتضيف نتيجة)
  const env = {
    sleep: async (ms) => { st.t += ms; }, now: () => st.t, aborted: () => st.abort,
    log: async (s, m, l) => { st.ev.push(['log', s]); },
    check: () => { st.n++; const d = st.stopWhen && st.stopWhen(st.n, st.t); return d ? { stop: true, code: d.code || 'verification', reason: d.reason || 'ظهر تحقق' } : { stop: false }; },
    find: (sels) => { const s = sels.find(x => st.present.has(x)); return s ? { sel: s } : null; },
    findVisible: (sels) => (st.busyUntil && st.t < st.busyUntil && sels.some(x => (st.busySel || []).includes(x))) ? { sel: 'busy' } : null,
    ready: (h) => !st.disabled.has(h.sel),
    isSensitive: (h) => st.sensitive.has(h.sel),
    markResults: () => ({ srcs: new Set(st.results.map(r => r.src)), seen: new Set(st.results.map(r => r.id)) }),
    listResults: (sels, before) => st.results.filter(r => r.appearAt <= st.t).map(r => ({ h: r, info: { tag: r.tag, parentTag: r.parentTag || '', src: r.src, w: r.w || 0, h: r.h || 0, complete: true, wasSeen: before.seen.has(r.id) } })),
    attach: (h, refs) => { st.ev.push(['attach', h.sel, refs.length]); },
    dropFiles: (h, refs) => { st.ev.push(['drop', h.sel, refs.length]); return !!st.dropOk; },
    typeInto: async (h, text, mode) => { st.ev.push(['type', h.sel, text]); },
    click: (h) => { st.ev.push(['click', h.sel]); if (st.clickAt[h.sel]) st.clickAt[h.sel](st); },
    fetchResult: async (h, dl, type) => { if (st.dlFail) throw new Error('فشل'); st.fetched++; return { uploadId: 'u1', mime: type + '/x', size: 10, total: 1, w: h.w || 0, h: h.h || 0 }; },
  };
  return { st, env };
}
const IMG = (src, w, h, extra) => ({ tag: 'IMG', src, w: w || 800, h: h || 600, ...extra });
// إعداد عام للاختبار (مش محدّدات موقع حقيقي): attach(اختياري) ← type ← click، وNتيجة حسب النوع، والمهلة الافتراضية حسب النوع.
const KC = {};
for (const [kind, type] of Object.entries(A.RESULT_TYPE)) KC[kind] = { url: 'https://flow.google.com/', steps: [
  { do: 'attach', sel: ['input[type="file"]'], optional: kind !== 'video' }, { do: 'type', sel: ['textarea'], text: '{prompt}' },
  { do: 'click', sel: ['button[aria-label*="Generate" i]'], optional: false }], busy: ['[role="progressbar"]'], result: { type, sel: ['img'], download: [] } };
const run = (pg, kind, site, task, extra) => E.runTask(pg.env, { A, pace: P, task: task || { task_id: 't1', prompt: 'P', seconds: 3.4 }, kind,
  kcfg: KC[kind], refs: [], mode: 'max', ...(extra || {}) });
"""


@needs_node
def test_engine_happy_path_runs_steps_in_order_and_downloads_the_newest_new_result():
    o = node(FAKE + """
const pg = page({ present: ['textarea', 'button[aria-label*="Generate" i]'], results: [IMG('https://old/1.png', 900, 900)],
  clickAt: { 'button[aria-label*="Generate" i]': (st) => { st.results.push({ id: 'n1', appearAt: st.t + 5000, ...IMG('https://new/small.png', 400, 400) }, { id: 'n2', appearAt: st.t + 5000, ...IMG('https://new/big.png', 1000, 800) }); } },
  busySel: ['[role="progressbar"]'], busyUntil: 20000 });
const r = await run(pg, 'image', 'flow', { task_id: 'a', prompt: 'قطة', seconds: 2 });
out({ r, ev: pg.st.ev.filter(e => e[0] !== 'log'), fetched: pg.st.fetched })
""")
    assert o["r"]["ok"] is True and o["r"]["w"] == 1000 and o["fetched"] == 1       # الأكبر من الجدد (القديمة ما بتنحسب)
    assert o["ev"] == [["type", "textarea", "قطة"], ["click", 'button[aria-label*="Generate" i]']]   # attach انتخطّت (ما في مراجع)


@needs_node
def test_engine_attaches_refs_and_templates_prompt_with_seconds():
    o = node(FAKE + """
const pg = page({ clickAt: { 'button[aria-label*="Generate" i]': (st) => { st.results.push({ id: 'v', appearAt: st.t + 1000, tag: 'VIDEO', src: 'blob:v', w: 1280, h: 720 }); } } });
const r = await run(pg, 'video', 'flow', { task_id: 's1c1', prompt: 'حركة بطيئة', seconds: 3.4 }, { refs: [{ name: 'final.png', mime: 'image/png', b64: 'AA==' }],
  kcfg: A.mergeConfig(A.DEFAULT_CONFIG, { sites: { flow: { kinds: { video: { steps: [
    { do: 'attach', sel: ['input[type="file"]'] }, { do: 'wait', ms: 100 }, { do: 'type', sel: ['textarea'], text: '{prompt} — {seconds} ثانية' },
    { do: 'click', sel: ['button[aria-label*="Generate" i]'] }] } } } } }).config.sites.flow.kinds.video });
out({ r, ev: pg.st.ev.filter(e => e[0] !== 'log') })
""")
    assert o["r"]["ok"] is True
    assert o["ev"] == [["attach", 'input[type="file"]', 1], ["type", "textarea", "حركة بطيئة — 3.4 ثانية"], ["click", 'button[aria-label*="Generate" i]']]


@needs_node
def test_engine_optional_steps_skip_but_required_missing_selector_stops_unknown_page():
    o = node(FAKE + """
// إرفاق اختياري ما انلقى + ما في مراجع ← تخطّي؛ بدون مراجع وبصندوق ناقص ← وقوف
const a = page({ present: ['textarea', 'button[aria-label*="Generate" i]'], clickAt: { 'button[aria-label*="Generate" i]': (st) => st.results.push({ id: 'n', appearAt: st.t, ...IMG('https://n/1.png') }) } });
const ra = await run(a, 'image', 'flow');
const b = page({ present: ['textarea'] });                                      // زر Generate مش موجود (غير optional)
const rb = await run(b, 'image', 'flow', null, { stepWaitMs: 3000 });
const c = page({ present: ['textarea', 'button[aria-label*="Generate" i]'], disabled: ['button[aria-label*="Generate" i]'] });
const rc = await run(c, 'image', 'flow', null, { stepWaitMs: 3000 });
const d = page({ present: ['button[aria-label*="Generate" i]'] });                // صندوق الكتابة غايب
const rd = await run(d, 'image', 'flow', null, { stepWaitMs: 3000 });
// اختياري + مراجع + حقل ملفات غايب ← بديل الإسقاط (إذا نجح)، وإلا تخطّي مسجّل
const e = page({ present: ['textarea', 'button[aria-label*="Generate" i]'], dropOk: true, clickAt: { 'button[aria-label*="Generate" i]': (st) => st.results.push({ id: 'n', appearAt: st.t, ...IMG('https://n/2.png') }) } });
const re = await run(e, 'image', 'flow', null, { refs: [{ name: 'r.png', mime: 'image/png', b64: 'AA==' }] });
// attach غير اختياري + مراجع + غايب ← وقوف (بدون تخمين بالإسقاط)
const f = page({ present: ['textarea', 'button[aria-label*="Generate" i]'], dropOk: true });
const rf = await run(f, 'video', 'flow', null, { refs: [{ name: 'r.png', mime: 'image/png', b64: 'AA==' }], stepWaitMs: 3000 });
out({ ra: ra.ok, rb, rc, rd, re: re.ok, drops: e.st.ev.filter(x => x[0] === 'drop'), rf, fetchedB: b.st.fetched, clicksB: b.st.ev.filter(x => x[0] === 'click').length })
""")
    assert o["ra"] is True and o["re"] is True and o["drops"] == [["drop", "textarea", 1]]
    for k in ("rb", "rc", "rd", "rf"):
        assert o[k]["stop"] is True and o[k]["code"] == "unknown_page" and o[k]["reason"], (k, o[k])
    assert o["rb"]["step"] == "step2:click" and o["rc"]["step"] == "step2:click" and o["rf"]["step"] == "step0:attach"
    assert "معطّل" in o["rc"]["reason"] and "ما لقيت" in o["rb"]["reason"]
    assert o["fetchedB"] == 0 and o["clicksB"] == 0


@needs_node
def test_engine_checks_for_stop_before_every_step_and_while_generating():
    o = node(FAKE + """
const mk = (stopAt) => page({ present: ['textarea', 'button[aria-label*="Generate" i]'], stopWhen: stopAt ? (n) => n === stopAt : null,
  clickAt: { 'button[aria-label*="Generate" i]': (st) => st.results.push({ id: 'n', appearAt: st.t + 8000, ...IMG('https://n/1.png') }) } });
const base = mk(0); const rb = await run(base, 'image', 'flow', null, { refs: [{ name: 'r', mime: 'image/png', b64: 'AA==' }] });
const total = base.st.n, res = [];
for (let n = 1; n <= total; n++) {
  const pg = mk(n); const r = await run(pg, 'image', 'flow', null, { refs: [{ name: 'r', mime: 'image/png', b64: 'AA==' }] });
  res.push([n, r.stop === true, r.code, pg.st.fetched, r.step]);
}
out({ ok: rb.ok, total, res })
""")
    assert o["ok"] is True and o["total"] >= 8
    for n, stopped, code, fetched, step in o["res"]:
        assert stopped and code == "verification" and fetched == 0 and step, (n, step)       # أي وقوف بأي نقطة = وقف كامل بلا تنزيل
    steps = {r[4] for r in o["res"]}
    assert "precheck" in steps and "generating" in steps and any(s.startswith("step") for s in steps)


@needs_node
def test_engine_waits_for_busy_and_times_out_by_kind():
    o = node(FAKE + """
// busy: النتيجة موجودة بس الموقع لسا مشغول ← ما بتنزّل قبل ما يخلص
const a = page({ present: ['textarea', 'button[aria-label*="Generate" i]'], busySel: ['[role="progressbar"]'], busyUntil: 60000,
  clickAt: { 'button[aria-label*="Generate" i]': (st) => st.results.push({ id: 'n', appearAt: st.t, ...IMG('https://n/1.png') }) } });
const ra = await run(a, 'image', 'flow');
// timeout: لا نتيجة أبداً — الحدّ حسب النوع (صوت 180، صورة 300، موسيقى 300، فيديو 900)
const t = async (kind, site, extraK) => {
  const pg = page({ present: ['textarea', 'button[aria-label*="Generate" i]', 'button[type="submit"]', 'button[aria-label*="Create" i]'] });
  const r = await run(pg, kind, site);
  return { r, t: pg.st.t };
};
const voice = await t('voice', 'elevenlabs'), image = await t('image', 'flow'), music = await t('music', 'flowmusic'), video = await t('video', 'flow');
out({ aT: a.st.t, aOk: ra.ok, voice, image, music, video })
""")
    assert o["aOk"] is True and o["aT"] >= 60000                      # ما نزّل قبل ما انتهى busy
    for k, sec in (("voice", 180), ("image", 300), ("music", 300), ("video", 900)):
        r = o[k]["r"]
        assert r["stop"] is True and r["code"] == "timeout" and r["step"] == "generating", (k, r)
        assert sec * 1000 <= o[k]["t"] <= sec * 1000 + 8000, (k, o[k]["t"])
        assert str(round(sec / 60)) in r["reason"] and "دقيقة" in r["reason"]


@needs_node
def test_engine_config_timeout_overrides_default_and_ignores_old_results():
    o = node(FAKE + """
const kc = A.mergeConfig(A.DEFAULT_CONFIG, { sites: { elevenlabs: { kinds: { voice: { timeoutSec: 60 } } } } }).config.sites.elevenlabs.kinds.voice;
// نتيجة صوت قديمة فقط (موجودة قبل الإرسال) + مهلة 60 ثانية ← timeout (ما بتنأخذ القديمة)
const pg = page({ present: ['textarea', 'button[aria-label*="Generate" i]'], results: [{ tag: 'AUDIO', src: 'https://old/a.mp3' }] });
const r = await run(pg, 'voice', 'elevenlabs', null, { kcfg: kc });
out({ r, t: pg.st.t, fetched: pg.st.fetched, to: A.timeoutFor('voice', kc) })
""")
    assert o["to"] == 60 and o["r"]["code"] == "timeout" and o["fetched"] == 0
    assert 60000 <= o["t"] <= 68000


@needs_node
def test_engine_stops_on_sensitive_field_cancel_and_download_failure():
    o = node(FAKE + """
const clicks = { 'button[aria-label*="Generate" i]': (st) => st.results.push({ id: 'n', appearAt: st.t, ...IMG('https://n/1.png') }) };
const s = page({ present: ['textarea', 'button[aria-label*="Generate" i]'], sensitive: ['textarea'] });
const rs = await run(s, 'image', 'flow');
const c = page({ present: ['textarea', 'button[aria-label*="Generate" i]'], clickAt: { 'button[aria-label*="Generate" i]': (st) => { st.abort = true; } } });
const rc = await run(c, 'image', 'flow');
const d = page({ present: ['textarea', 'button[aria-label*="Generate" i]'], dlFail: true, clickAt: clicks });
const rd = await run(d, 'image', 'flow');
const bad = await run(page(), 'image', 'flow', null, { kcfg: { steps: [{ do: 'fly' }], result: { type: 'image', sel: ['img'] } } });
out({ rs, typedS: s.st.ev.filter(e => e[0] === 'type').length, rc, rd, bad })
""")
    assert o["rs"]["code"] == "unknown_page" and o["typedS"] == 0                    # ما بنكتب بحقل حساس
    assert o["rc"]["code"] == "cancelled"
    assert o["rd"]["code"] == "download_failed" and o["rd"]["step"] == "download"
    assert o["bad"]["code"] == "error"


@needs_node
def test_engine_audio_and_video_results_pick_the_latest_new_element():
    o = node(FAKE + """
const mkClick = (list) => ({ 'button[aria-label*="Generate" i]': (st) => list.forEach((r, i) => st.results.push({ id: 'n' + i, appearAt: st.t + 100 * i, ...r })) });
const a = page({ present: ['textarea', 'button[aria-label*="Generate" i]'], results: [{ tag: 'AUDIO', src: 'https://old.mp3' }],
  clickAt: mkClick([{ tag: 'AUDIO', src: 'https://new1.mp3' }, { tag: 'SOURCE', parentTag: 'AUDIO', src: 'https://new2.mp3' }, { tag: 'VIDEO', src: 'https://nope.mp4' }]) });
let picked = null; const f0 = a.env.fetchResult; a.env.fetchResult = async (h, dl, type) => { picked = h.src; return f0(h, dl, type); };
const ra = await run(a, 'ahat', 'elevenlabs');
out({ ok: ra.ok, picked })
""")
    assert o["ok"] is True and o["picked"] == "https://new2.mp3"


# ───────────────────────── قيود ساكنة: الأمان والتبويب الواحد والاتصال ─────────────────────────
JS_FILES = ["background.js", "content.js", "popup.js", "options.js", "offscreen.js", "lib/pace.js", "lib/detect.js", "lib/adapters.js", "lib/engine.js"]


def all_js():
    return {n: read(n) for n in JS_FILES}


def test_no_file_reads_or_writes_credentials_and_only_adapters_detect_ui_mention_them():
    files = all_js()
    for name, src in files.items():
        if name in ("lib/adapters.js", "lib/detect.js", "popup.js", "options.js"):
            continue
        assert "password" not in src.lower(), name                   # background/content/engine ما بيعرفوا الكلمة أصلاً
    ad = files["lib/adapters.js"]
    # adapters/detect بيكشفوا وجود الحقل/النوع فقط — ولا مرة قراءة قيمة
    for src in (ad, files["lib/detect.js"]):
        assert not re.search(r"password[^\n]{0,80}\.(value|textContent|innerText|innerHTML)", src, re.I)
        assert not re.search(r"""type=["']?password["']?\]['"]?\)\s*\.\s*value""", src, re.I)
    assert "getAttribute(\"type\")" in ad and "isSensitiveEl" in ad and "SENSITIVE_SEL" in ad
    # لا كتابة بحقول: كل typeInto/attach يمرّ بفحص الحساسية بالمحرّك
    assert "env.isSensitive(w.h)" in read("lib/engine.js")
    allsrc = "".join(files.values())
    for bad in ("document.cookie", "chrome.cookies", "localStorage", "sessionStorage", "indexedDB", "navigator.credentials", "autofill"):
        assert bad not in allsrc, bad
    # التوكن ما بينطبع/بينكتب بالسجل
    for name in ("background.js", "content.js"):
        assert not re.search(r"log\([^)]*(token|c\.token)", files[name]), name
        assert not re.search(r"console\.\w+\([^)]*token", files[name], re.I), name


def test_one_tab_only_even_for_the_daily_selftest_and_no_auto_resume():
    bg = read("background.js")
    assert bg.count("chrome.tabs.create") == 1                        # تبويب واحد فقط (ensureTab)
    assert "window.open" not in "".join(all_js().values())
    assert "if (RUN.tabClosed) throw" in bg                           # ما بيفتح تاني لو الأول اتسكّر أثناء الشغل/الفحص
    assert bg.count("loop();") == 2                                   # الحلقة بتبدأ بس من start وresume (ضغطة المالك)
    assert "setInterval(() => loop" not in bg
    # الفحص الذاتي يستخدم نفس التبويب (openInTab ← ensureTab)، وما بيولّد أي شي ولا بيرفع نتائج
    m = re.search(r"async function selftestAll.*?\nasync function autoSelftest", bg, re.S)
    assert m, "selftestAll غايبة"
    body = m.group(0)
    assert "openInTab(" in body and "chrome.tabs.create" not in body
    assert '"run"' not in body and "/result" not in body and "doTask" not in body and "loop(" not in body
    assert '"selftest"' in body and "/api/ext/selftest" in body
    # المنبّه بيشغّل الفحص بس: ما بيبدأ حلقة توليد ولا بيستأنف
    h = re.search(r"chrome\.alarms\.onAlarm\.addListener\([^\n]*\n", bg)
    assert h and "autoSelftest" in h.group(0) and "loop" not in h.group(0) and "resume" not in h.group(0)
    a = re.search(r"async function autoSelftest.*?\n}\n", bg, re.S).group(0)
    assert "st.hold" in a and "RUN.on" in a and "loop" not in a        # ما بيلمس التبويب وقت تشغيل أو وقوف ينتظر المالك
    assert "chrome.alarms.create" in bg and "periodInMinutes: 1440" in bg
    # الرجوع بعد وقوف يدوي فقط: «كمّل» بتتأكد من سلامة الصفحة أولاً
    assert "async function resume" in bg and "snap.stop" in bg


def test_extension_talks_only_to_localhost_plus_the_declared_generation_sites():
    allowed = {"localhost", "127.0.0.1", "gemini.google.com", "chatgpt.com", "aistudio.google.com", "flow.google.com", "elevenlabs.io", "flowmusic.app", "www.flowmusic.app"}
    found = set()
    for p in list(EXT.glob("*.js")) + list(EXT.glob("lib/*.js")) + list(EXT.glob("*.html")) + [EXT / "manifest.json"]:
        for m in re.finditer(r"""(?:https?|wss?)://([A-Za-z0-9.\-*]+)""", p.read_text(encoding="utf-8")):
            found.add(m.group(1))
    assert found <= allowed, found - allowed
    files = all_js()
    allsrc = "".join(files.values())
    for bad in ("XMLHttpRequest", "WebSocket", "sendBeacon", "EventSource", "importScripts(\"http", "chrome.webRequest", "chrome.scripting", "eval(", "new Function("):
        assert bad not in allsrc, bad
    # التنزيل (v0.3 — التجربة السريعة): بس بالـ background، وبمجلد التنزيلات (VidPattern/…)، مرة وحدة
    for name, src in files.items():
        if name != "background.js":
            assert "chrome.downloads" not in src, name
    assert files["background.js"].count("chrome.downloads.download(") == 1
    for h in (EXT / "popup.html", EXT / "options.html"):
        assert not re.search(r"<(script|link|img|iframe)[^>]+(?:src|href)=[\"']https?:", h.read_text(encoding="utf-8")), h
    bg = files["background.js"]
    calls = [m.start() for m in re.finditer(r"\bfetch\(", bg)]
    assert len(calls) == 3
    for i in calls:
        assert "baseOf(c)" in bg[i:i + 90], bg[i:i + 90]                     # كل fetch بالـ background للاستوديو المحلي بعد فحص localhost
    assert "LOCAL_RX" in bg and "function baseOf" in bg
    c = files["content.js"]
    assert c.count("fetch(") == 1 and 'credentials: "include"' in c            # الوحيد للخارج: مصدر نتيجة الصفحة نفسها
    assert "fetch(" not in files["options.js"] and "LOCAL_RX.test(base)" in files["popup.js"]
    assert "fetch(" not in files["lib/adapters.js"] + files["lib/engine.js"] + files["lib/detect.js"] + files["lib/pace.js"]


def test_background_follows_the_contract_endpoints_and_control_fields():
    bg = read("background.js")
    for needle in ('"/tasks?kind="', "ctrl.only", "step_mode", "one_by_one", '"/result"', 'form.append("task_id"', 'form.append("kind"', 'form.append("site"',
                   '"/api/ext/config"', '"/api/ext/version"', '"/api/ext/selftest"', "A.compareVersions", "refreshConfig", "loadConfig",
                   "adapterConfig", "ext/asset/", "A.pickSite", 'command: "pause"', "ctrl.step_mode"):
        assert needle in bg, needle
    # الرجوع للمخزّن لو الخادم مش متاح
    assert re.search(r"catch \{ return loadConfig\(\); \}", bg)
    # الاستئناف دايماً يدوي: ما في أي استدعاء control run تلقائي بعد وقوف
    assert bg.count('setControl({ command: "run"') == 2                        # start + resume فقط
    # الوقوف: حفظ مكان + تنبيه + hold
    assert '"/stop"' in bg and "notify(" in bg and "hold: true" in bg
    # ما بنرفع شي بعد إلغاء/وقوف
    assert "cancelled" in bg


def test_content_chunks_large_media_instead_of_one_huge_message():
    c = read("content.js")
    assert "A.chunkPlan(blob.size)" in c and '"chunk"' in c and "A.uploadAllowed(blob.size)" in c and "blob.slice(" in c
    bg = read("background.js")
    assert "storeChunk" in bg and "takeUpload" in bg and "MAX_UPLOAD_BYTES" in bg
    # الردّ النهائي من الصفحة بدون بيانات الملف نفسها
    assert "uploadId" in c and "b64" in c and "return { uploadId: id" in c
    for ev in ("navigator.webdriver", "userAgent", "solveCaptcha", "grecaptcha", "2captcha", "canvas.toDataURL"):
        assert ev not in c and ev not in read("background.js") and ev not in read("lib/engine.js"), ev


def test_popup_exposes_kinds_sites_badge_buttons_modes_and_arabic_warnings():
    h, j = read("popup.html"), read("popup.js")
    for i in ("script", "kind", "site", "mode", "stepMode", "start", "pause", "resume", "cancel", "retry", "retryId", "retryPrompt", "tasks", "selftest", "log", "siteBadge"):
        assert f'id="{i}"' in h, i
    for k in ("voice", "image", "video", "ahat", "music"):
        assert f'<option value="{k}">' in h, k
    for m in ("natural", "fast", "max"):
        assert f'value="{m}"' in h and m in j
    assert "غير مجرّب" in j and "A.sitesForKind" in j and "verified" in j
    assert 'value="one_by_one"' in h and 'value="all"' in h and "لقطة لقطة مع مراجعة" in h and "الكل مرة وحدة" in h
    assert "احتمال" in h and "يلاحظ الأتمتة" in j                                   # تحذير السرعة ظاهر
    assert "checkedOnly" in j and "only:" in j and "/ext/retry" in j and "task_id: id" in j
    assert 'type: "control", command: "stop"' in j and 'command: "pause"' in j and 'type: "resume"' in j
    # ما في أزرار للمؤجّل: تعديل جزء من الصورة / استنساخ الصوت
    allui = h + j + read("options.html") + read("options.js")
    for deferred in ("استنساخ", "قناع", "inpaint", "clone"):
        assert deferred not in allui, deferred
