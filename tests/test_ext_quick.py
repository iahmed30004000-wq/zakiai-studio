"""الإضافة v0.3: تجربة سريعة مستقلة + خطوات المحرّك الجديدة + إعداد Flow/Flow Music الحقيقي + تقارير بنية الصفحة.

كلها بلا اتصال بمواقع حقيقية: المحرّك بصفحة وهمية (node)، والإعداد الافتراضي بجانبي JS وPython لازم يتطابقوا.
"""

import json
import os
import re
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from test_ext_multisite import EXT, FAKE, node, needs_node, read  # noqa: E402,F401
from a_helpers import env  # noqa: E402,F401

import config  # noqa: E402
import ext_config  # noqa: E402


# ───────────────────────── تطابق الإعداد الافتراضي بين الإضافة والخادم ─────────────────────────
@needs_node
def test_python_defaults_and_extension_defaults_are_identical_after_sanitising():
    """الإضافة بتسحب إعداد الخادم وبيغلب المضمّن: لو اختلفوا، التصليح بجهة بيضيع بالتانية."""
    py = json.dumps(ext_config.DEFAULTS)
    o = node("""
const py = JSON.parse(%s);
const a = A.sanitizeConfig(A.DEFAULT_CONFIG, A.DEFAULT_CONFIG), b = A.sanitizeConfig(py, A.DEFAULT_CONFIG);
const diffs = [];
for (const k of Object.keys(a.sites)) if (JSON.stringify(a.sites[k]) !== JSON.stringify(b.sites[k])) diffs.push(k);
out({ diffs, versionJs: A.DEFAULT_CONFIG.version, versionPy: py.version, warnings: (() => { const w = []; A.sanitizeConfig(py, A.DEFAULT_CONFIG, w); return w; })() })
""" % json.dumps(py))
    assert o["diffs"] == [] and o["warnings"] == [] and o["versionJs"] == o["versionPy"]


def test_python_defaults_pass_the_server_validation():
    ext_config.validate_all(ext_config.DEFAULTS["sites"])


# ───────────────────────── العناوين والإعداد الحقيقي ─────────────────────────
def test_manifest_matches_real_hosts_and_has_download_permissions():
    m = json.loads(read("manifest.json"))
    assert m["version"] == "0.4.0" and "downloads" in m["permissions"] and "offscreen" in m["permissions"]
    hosts = {h.replace("https://", "").replace("/*", "") for h in m["host_permissions"] if h.startswith("https://")}
    assert hosts == {"gemini.google.com", "chatgpt.com", "aistudio.google.com", "flow.google.com", "elevenlabs.io", "flowmusic.app", "www.flowmusic.app"}
    assert "labs.google" not in json.dumps(m)                                       # عنوان Flow القديم
    cs = {u.replace("https://", "").replace("/*", "") for u in m["content_scripts"][0]["matches"]}
    assert cs == hosts


@needs_node
def test_real_flow_and_flowmusic_selectors_are_the_ones_read_from_the_live_pages():
    o = node("""
const f = DEF.sites.flow, fm = DEF.sites.flowmusic;
out({ flowHosts: f.hosts, flowNew: f.newUrl, composer: f.selftest.composer, fmHosts: fm.hosts, fmNew: fm.newUrl, fmComposer: fm.selftest.composer,
      imageSteps: f.kinds.image.steps.map(s => [s.do, s.sel[0], s.if || null, s.needs || null]), send: f.kinds.image.steps.at(-1),
      fmSend: fm.kinds.music.steps.at(-1), reveal: fm.kinds.music.result.reveal, imgRes: f.kinds.image.result.sel })
""")
    assert o["flowHosts"] == ["flow.google.com"] and o["flowNew"] == "https://flow.google.com/"
    assert o["composer"][0] == 'div.ProseMirror[role="textbox"]'
    assert o["fmHosts"] == ["flowmusic.app", "www.flowmusic.app"] and o["fmNew"] == "https://www.flowmusic.app/"
    assert o["fmComposer"][0] == 'textarea[aria-label="Chat message"]' and o["fmSend"]["sel"] == ['button[aria-label="Send message"]']
    assert o["send"]["sel"] == ['button[aria-label="Start generation"]'] and o["send"]["optional"] is False
    steps = {tuple(x[:2]): x for x in o["imageSteps"]}
    assert ("click", "button.agent-mode-chip") in steps and steps[("click", "button.agent-mode-chip")][2] == "pressed"   # وضع Agent مطفّي
    assert any(x[1].endswith("::contains(x1)") for x in o["imageSteps"])                                              # عدد النتائج 1 (حماية الرصيد)
    assert any(x[1].endswith("::contains({aspect})") for x in o["imageSteps"])
    assert o["reveal"] == ['button[aria-label*="Play" i]'] and o["imgRes"][0] == 'img[alt*="Tile displaying" i]'


# ───────────────────────── المحدّدات: contains / قالب / ضغط / ممنوعات ─────────────────────────
@needs_node
def test_selector_text_matching_template_and_danger_words():
    o = node("""
const el = (text, aria, extra) => ({ innerText: text, getAttribute: (n) => n === 'aria-label' ? (aria || null) : null, ...extra });
const doc = { querySelectorAll: (css) => css === 'button' ? [el('crop_16_9\\n16:9'), el('crop_9_16\\n9:16'), el('x1'), el('', 'Close panel')] : [] };
global.document = doc;
const q = (sel) => A.all([sel]).map(e => e.innerText || e.getAttribute('aria-label'));
const pressed = (attrs, cls, closest) => A.isPressed({ getAttribute: (n) => attrs[n] || null, classList: { contains: (c) => (cls || []).includes(c) }, closest: () => closest || null });
out({ r916: q('button::contains(9:16)'), r169: q('button::contains(16:9)'), x1: q('button::contains(x1)'), aria: q('button::contains(close panel)'), plain: q('button').length, none: q('button::contains(zzz)'),
      tpl: A.resolveSels(['b::contains({aspect})'], { aspect: '16:9' }), tplDefault: A.resolveSels(['b::contains({aspect})'], {}), bad: q('div[[[::contains(x)'),
      parse: [A.parseSel('a::contains(b)'), A.parseSel('::contains(Frames)'), A.parseSel('plain')],
      pressed: [pressed({ 'aria-pressed': 'true' }), pressed({ 'aria-checked': 'true' }), pressed({ 'aria-selected': 'true' }), pressed({ 'aria-pressed': 'false' }), pressed({}, ['mat-button-toggle-checked']), pressed({}, [], {}), pressed({})],
      danger: ['button[aria-label="Delete project"]', 'button::contains(Upgrade)', 'a[href*="checkout"]', 'button::contains(Sign out)', 'button[aria-label="Start generation"]', 'button.agent-mode-chip', 'button::contains(New project)', 'button[aria-label="Settings trigger"]'].map(A.isSensitiveSelector) })
""")
    assert o["r916"] == ["crop_9_16\n9:16"] and o["r169"] == ["crop_16_9\n16:9"] and o["x1"] == ["x1"] and o["aria"] == ["Close panel"]
    assert o["plain"] == 4 and o["none"] == [] and o["bad"] == []
    assert o["tpl"] == ["b::contains(16:9)"] and o["tplDefault"] == ["b::contains(9:16)"]            # الافتراضي عمودي (فريم الاستوديو)
    assert o["parse"] == [{"css": "a", "text": "b"}, {"css": "*", "text": "frames"}, {"css": "plain", "text": None}]
    assert o["pressed"] == [True, True, True, False, True, True, False]
    assert o["danger"] == [True, True, True, True, False, False, False, False]


@needs_node
def test_parse_steps_new_fields_are_validated():
    o = node("""
const bad = [
  { do: 'type', sel: ['a'], if: 'pressed' }, { do: 'click', sel: ['a'], if: 'maybe' }, { do: 'click', sel: ['a'], via: 'drop' }, { do: 'attach', sel: ['a'], via: 'fly' },
  { do: 'click', sel: ['a'], needs: 'money' }, { do: 'click', sel: ['a'], waitMs: 100 }, { do: 'click', sel: ['a'], waitMs: 99999 }, { do: 'click', sel: ['button[aria-label="Delete"]'] },
].map(s => A.parseSteps({ steps: [s] }).errors.length > 0);
const ok = A.parseSteps({ steps: [{ do: 'click', sel: ['a'], if: 'unpressed', waitMs: 1500, needs: 'refs' }, { do: 'attach', sel: ['b'], via: 'paste' }] });
out({ bad, ok })
""")
    assert all(o["bad"]), o["bad"]
    assert o["ok"]["errors"] == [] and o["ok"]["steps"][0] == {"do": "click", "sel": ["a"], "optional": False, "needs": "refs", "if": "unpressed", "waitMs": 1500}
    assert o["ok"]["steps"][1]["via"] == "paste"


@needs_node
def test_result_reveal_is_kept_validated_and_rejects_dangerous_selectors():
    o = node("""
const mk = (rv) => A.mergeConfig(A.DEFAULT_CONFIG, { sites: { flowmusic: { kinds: { music: { result: { type: 'audio', sel: ['audio'], reveal: rv } } } } } });
const good = mk(['button[aria-label*="Play" i]']), bad = mk(['button[aria-label="Delete song"]']);
out({ good: good.config.sites.flowmusic.kinds.music.result.reveal, goodW: good.warnings, bad: bad.config.sites.flowmusic.kinds.music.result.reveal, badW: bad.warnings.length })
""")
    assert o["good"] == ['button[aria-label*="Play" i]'] and o["goodW"] == []
    assert o["bad"] == ['button[aria-label*="Play" i]'] and o["badW"] >= 1                 # الرجوع للافتراضي + تحذير


# ───────────────────────── المحرّك: needs / if / via / waitMs / reveal / diag ─────────────────────────
ENG = FAKE + """
const mkcfg = (steps, extra) => ({ url: 'https://flow.google.com/', steps, busy: [], result: { type: 'image', sel: ['img'], download: [] }, ...(extra || {}) });
const gen = (sel) => ({ [sel]: (st) => st.results.push({ id: 'n', appearAt: st.t, ...IMG('https://n/1.png', 1000, 1000) }) });
const base = (o) => { const pg = page(o); pg.env.pressed = (h) => (pg.st.pressedSet || new Set()).has(h.sel); return pg; };
"""


@needs_node
def test_engine_needs_refs_skips_steps_when_there_are_no_references():
    o = node(ENG + """
const steps = [{ do: 'click', sel: ['#plus'], needs: 'refs', optional: true }, { do: 'attach', sel: ['input[type="file"]'], optional: true }, { do: 'type', sel: ['textarea'], text: '{prompt}' }, { do: 'click', sel: ['#go'] }];
const a = base({ present: ['#plus', 'input[type="file"]', 'textarea', '#go'], clickAt: gen('#go') });
const ra = await E.runTask(a.env, { A, pace: P, task: { task_id: 't', prompt: 'p' }, kind: 'image', kcfg: mkcfg(steps), refs: [], mode: 'max' });
const b = base({ present: ['#plus', 'input[type="file"]', 'textarea', '#go'], clickAt: gen('#go') });
const rb = await E.runTask(b.env, { A, pace: P, task: { task_id: 't', prompt: 'p' }, kind: 'image', kcfg: mkcfg(steps), refs: [{ name: 'r', mime: 'image/png', b64: 'AA==' }], mode: 'max' });
out({ ra: ra.ok, evA: a.st.ev.filter(e => e[0] !== 'log').map(e => e[0] + ':' + e[1]), rb: rb.ok, evB: b.st.ev.filter(e => e[0] !== 'log').map(e => e[0] + ':' + e[1]) })
""")
    assert o["ra"] is True and o["evA"] == ["type:textarea", "click:#go"]                          # بلا مراجع: ما بينفتح حوار الإرفاق أصلاً
    assert o["rb"] is True and o["evB"] == ["click:#plus", "attach:input[type=\"file\"]", "type:textarea", "click:#go"]


@needs_node
def test_engine_click_if_pressed_or_unpressed_only_clicks_when_the_state_differs():
    o = node(ENG + """
const steps = [
  { do: 'click', sel: ['#agent'], if: 'pressed', optional: true },       // شريحة Agent: بنطفّيها لو شغّالة
  { do: 'click', sel: ['#x1'], if: 'unpressed', optional: true },        // عدد النتائج: بنثبّته لو مش مثبّت
  { do: 'click', sel: ['#aspect'], if: 'unpressed', optional: true },
  { do: 'type', sel: ['textarea'], text: '{prompt}' }, { do: 'click', sel: ['#go'] }];
const run1 = async (pressedSet) => { const pg = base({ present: ['#agent', '#x1', '#aspect', 'textarea', '#go'], pressedSet: new Set(pressedSet), clickAt: gen('#go') });
  const r = await E.runTask(pg.env, { A, pace: P, task: { task_id: 't', prompt: 'p' }, kind: 'image', kcfg: mkcfg(steps), refs: [], mode: 'max' });
  return { ok: r.ok, clicks: pg.st.ev.filter(e => e[0] === 'click').map(e => e[1]) }; };
out({ agentOnNothingSet: await run1(['#agent']), allSet: await run1(['#x1', '#aspect']), noneSet: await run1([]) })
""")
    assert o["agentOnNothingSet"] == {"ok": True, "clicks": ["#agent", "#x1", "#aspect", "#go"]}
    assert o["allSet"] == {"ok": True, "clicks": ["#go"]}                                         # الاثنين مضغوطين أصلاً، وAgent مش مضغوط ← ما انضغط شي
    assert o["noneSet"] == {"ok": True, "clicks": ["#x1", "#aspect", "#go"]}


@needs_node
def test_engine_aspect_template_uses_the_task_or_the_vertical_default():
    o = node(ENG + """
const steps = [{ do: 'click', sel: ['b::contains({aspect})'], optional: true }, { do: 'type', sel: ['textarea'], text: '{prompt}' }, { do: 'click', sel: ['#go'] }];
const seen = [];
const run1 = async (task) => { const pg = base({ present: ['b::contains(16:9)', 'b::contains(9:16)', 'textarea', '#go'], clickAt: gen('#go') });
  await E.runTask(pg.env, { A, pace: P, task: { task_id: 't', prompt: 'p', ...task }, kind: 'image', kcfg: mkcfg(steps), refs: [], mode: 'max' });
  return pg.st.ev.filter(e => e[0] === 'click').map(e => e[1])[0]; };
out({ def: await run1({}), wide: await run1({ aspect: '16:9' }) })
""")
    assert o["def"] == "b::contains(9:16)" and o["wide"] == "b::contains(16:9)"


@needs_node
def test_engine_attach_via_drop_and_paste_target_the_found_element():
    o = node(ENG + """
const run1 = async (via) => { const steps = [{ do: 'attach', sel: ['#composer'], via }, { do: 'type', sel: ['#composer'], text: '{prompt}' }, { do: 'click', sel: ['#go'] }];
  const pg = base({ present: ['#composer', '#go'], clickAt: gen('#go') }); const pasted = [];
  pg.env.pasteFiles = (h, refs) => { pasted.push([h.sel, refs.length]); return true; };
  const r = await E.runTask(pg.env, { A, pace: P, task: { task_id: 't', prompt: 'p' }, kind: 'image', kcfg: mkcfg(steps), refs: [{ name: 'r', mime: 'image/png', b64: 'AA==' }], mode: 'max' });
  return { ok: r.ok, ev: pg.st.ev.filter(e => ['attach', 'drop'].includes(e[0])).map(e => e.join(':')), pasted }; };
out({ paste: await run1('paste'), drop: await run1('drop'), input: await run1('input') })
""")
    assert o["paste"] == {"ok": True, "ev": [], "pasted": [["#composer", 1]]}
    assert o["drop"] == {"ok": True, "ev": ["drop:#composer:1"], "pasted": []}
    assert o["input"]["ev"] == ["attach:#composer:1"] and o["input"]["pasted"] == []


@needs_node
def test_engine_optional_step_waits_briefly_and_waitms_overrides():
    o = node(ENG + """
const t = async (steps) => { const pg = base({ present: ['textarea', '#go'], clickAt: gen('#go') });
  const r = await E.runTask(pg.env, { A, pace: P, task: { task_id: 't', prompt: 'p' }, kind: 'image', kcfg: mkcfg(steps), refs: [], mode: 'max' });
  return { ok: r.ok, t: pg.st.t }; };
const tail = [{ do: 'type', sel: ['textarea'], text: '{prompt}' }, { do: 'click', sel: ['#go'] }];
const none = await t(tail);
const two = await t([{ do: 'click', sel: ['#missing'], optional: true }, { do: 'click', sel: ['#missing2'], optional: true, waitMs: 1000 }, ...tail]);
out({ ok: none.ok && two.ok, extra: two.t - none.t })
""")
    assert o["ok"] is True
    assert 5500 <= o["extra"] <= 7500          # 5000 (افتراضي الاختياري) + 1000 (waitMs) + هوامش التقطيع — مش 40000 (20 ثانية × 2)


@needs_node
def test_engine_reveal_clicks_play_when_no_result_appears_and_never_more_than_three_times():
    o = node(ENG + """
const kcfg = (reveal) => ({ url: 'https://www.flowmusic.app/', steps: [{ do: 'type', sel: ['textarea'], text: '{prompt}' }, { do: 'click', sel: ['#send'] }], busy: [],
  result: { type: 'audio', sel: ['audio'], download: [], reveal }, timeoutSec: 60 });
const run1 = async (reveal, appear) => {
  const pg = base({ present: ['textarea', '#send', '#play'], clickAt: { '#play': (st) => { if (appear) st.results.push({ id: 'a', appearAt: st.t, tag: 'AUDIO', src: 'blob:x' }); } } });
  const orig = pg.env.findVisible; pg.env.findVisible = (sels) => (sels.includes('#play') && pg.st.present.has('#play') ? { sel: '#play' } : orig(sels));
  const r = await E.runTask(pg.env, { A, pace: P, task: { task_id: 't', prompt: 'p' }, kind: 'music', kcfg: kcfg(reveal), refs: [], mode: 'max' });
  return { r: r.ok ? 'ok' : r.code, plays: pg.st.ev.filter(e => e[0] === 'click' && e[1] === '#play').length }; };
out({ withReveal: await run1(['#play'], true), neverAppears: await run1(['#play'], false), noReveal: await run1([], true) })
""")
    assert o["withReveal"] == {"r": "ok", "plays": 1}
    assert o["neverAppears"] == {"r": "timeout", "plays": 3}                                        # حدّ 3 ضغطات
    assert o["noReveal"]["plays"] == 0 and o["noReveal"]["r"] == "timeout"


@needs_node
def test_engine_attaches_diag_to_unknown_page_timeout_and_download_failed_only():
    o = node(ENG + """
const mk = (o) => { const pg = base(o); pg.env.diagnose = () => ({ host: 'x', buttons: [{ t: 'button', aria: 'Go' }] }); return pg; };
const steps = [{ do: 'type', sel: ['textarea'], text: '{prompt}' }, { do: 'click', sel: ['#go'] }];
const run1 = (pg, extra) => E.runTask(pg.env, { A, pace: P, task: { task_id: 't', prompt: 'p' }, kind: 'image', kcfg: mkcfg(steps, extra), refs: [], mode: 'max', stepWaitMs: 1500 });
const unknown = await run1(mk({ present: ['textarea'] }));
const timeout = await run1(mk({ present: ['textarea', '#go'] }), { timeoutSec: 30 });
const dl = await run1(mk({ present: ['textarea', '#go'], dlFail: true, clickAt: gen('#go') }));
const verification = await run1(mk({ present: ['textarea', '#go'], stopWhen: () => ({ code: 'verification' }) }));
const noEnvDiag = page({ present: ['textarea'] });
const nd = await E.runTask(noEnvDiag.env, { A, pace: P, task: { task_id: 't', prompt: 'p' }, kind: 'image', kcfg: mkcfg(steps), refs: [], mode: 'max', stepWaitMs: 1500 });
out({ unknown: [unknown.code, !!unknown.diag], timeout: [timeout.code, !!timeout.diag], dl: [dl.code, !!dl.diag], verification: [verification.code, !!verification.diag], nd: [nd.code, 'diag' in nd] })
""")
    assert o["unknown"] == ["unknown_page", True] and o["timeout"] == ["timeout", True] and o["dl"] == ["download_failed", True]
    assert o["verification"] == ["verification", False]                                              # التحقق ما بنرفق معه شي: بيوقف وبس
    assert o["nd"] == ["unknown_page", False]


# ───────────────────────── كاشف الوقوف: reCAPTCHA المخفي ما بيوقف ─────────────────────────
@needs_node
def test_hidden_recaptcha_badge_does_not_stop_but_a_visible_challenge_does():
    o = node("""
const frame = (title, w, visible) => ({ src: 'https://www.google.com/recaptcha/api2/anchor', title, getClientRects: () => visible ? [{}] : [], getBoundingClientRect: () => ({ width: w }) });
const run = (frames, text) => {
  global.location = { host: 'flow.google.com' };
  global.getComputedStyle = (f) => ({ visibility: f.__hidden ? 'hidden' : 'visible' });
  global.document = { body: { innerText: text || 'Start creating' }, querySelectorAll: (sel) => sel === 'iframe' ? frames : [], querySelector: () => null };
  const snap = A.snapshot({ hosts: ['flow.google.com'] }, null);
  return { captchaFrame: snap.has.captchaFrame, decision: D.decideStop(snap) };
};
const hiddenBadge = frame('reCAPTCHA', 256, false);                    // شارة v3: موجودة بالـ DOM بس مخفية
const hiddenByStyle = { ...frame('reCAPTCHA', 256, true), __hidden: true };
const challenge = frame('recaptcha challenge expires in two minutes', 400, true);
out({ hidden: run([hiddenBadge]), hiddenStyle: run([hiddenByStyle]), tiny: run([frame('reCAPTCHA', 10, true)]), visible: run([challenge]),
      footer: run([], 'This site is protected by reCAPTCHA and the Google Privacy Policy and Terms of Service apply.'), real: run([], 'Please complete the captcha to continue') })
""")
    assert o["hidden"]["captchaFrame"] is False and o["hidden"]["decision"] == {"stop": False}
    assert o["hiddenStyle"]["captchaFrame"] is False and o["tiny"]["captchaFrame"] is False
    assert o["visible"]["captchaFrame"] is True and o["visible"]["decision"]["code"] == "verification"
    assert o["footer"]["decision"] == {"stop": False}                                                   # جملة «protected by reCAPTCHA» ما هي تحقق
    assert o["real"]["decision"]["code"] == "verification"


@needs_node
def test_diagnose_reports_ui_labels_only_never_page_text_or_field_values():
    o = node("""
const el = (tag, attrs, text, extra) => ({ tagName: tag.toUpperCase(), id: (attrs && attrs.id) || '', className: (attrs && attrs.class) || '', innerText: text || '', value: 'SECRET-VALUE', disabled: false,
  getAttribute: (n) => (attrs && attrs[n]) || null, classList: { contains: () => false }, closest: () => null, getClientRects: () => [{}], getBoundingClientRect: () => ({ width: 120 }), ...(extra || {}) });
const all = { 'textarea, [contenteditable="true"], [role="textbox"], input[type="text"]': [el('div', { role: 'textbox', 'aria-label': 'What do you want to create?', class: 'ProseMirror' }, 'my private chat prompt text')],
  'button, [role=button], [role=radio], [role=tab], a[download]': [el('button', { 'aria-label': 'Start generation' }, 'arrow_forward'), el('button', { 'aria-label': 'Settings trigger', 'aria-pressed': 'true' }, 'x'.repeat(100))],
  'input[type="file"]': [{ accept: 'image/*' }], 'img, video, audio': [{ tagName: 'IMG', naturalWidth: 1376, naturalHeight: 768, currentSrc: 'https://flow.google.com/asb/ANqvLO?token=abc' }, { tagName: 'VIDEO', videoWidth: 1, videoHeight: 1, currentSrc: 'blob:https://x/1' }],
  'iframe': [], '[role="dialog"], mat-dialog-container, .cdk-overlay-pane': [] };
global.location = { host: 'flow.google.com', pathname: '/project/789394ac-26de-4c2d-8a2b-e382bfbab732' };
global.getComputedStyle = () => ({ visibility: 'visible' });
global.document = { body: { innerText: 'SECRET PAGE TEXT' }, querySelectorAll: (sel) => all[sel] || [] };
const d = A.diagnose(); const raw = JSON.stringify(d);
out({ d, leaks: ['SECRET-VALUE', 'SECRET PAGE TEXT', 'my private chat', 'token=abc'].filter(x => raw.includes(x)) })
""")
    d = o["d"]
    assert o["leaks"] == [] and d["path"] == "/project/:id" and d["host"] == "flow.google.com"
    assert d["composers"][0]["aria"] == "What do you want to create?" and d["buttons"][0]["aria"] == "Start generation"
    assert d["buttons"][1]["pressed"] is True and len(d["buttons"][1]["text"]) <= 30
    assert d["media"][0] == {"t": "img", "w": 1376, "h": 768, "src": "flow.google.com"} and d["media"][1]["src"] == "blob"
    assert d["fileInputs"] == ["image/*"] and d["captchaVisible"] is False


# ───────────────────────── قيود ساكنة: التجربة السريعة والتنزيل ─────────────────────────
def test_quick_run_reuses_the_one_tab_engine_and_never_touches_studio_control():
    bg = read("background.js")
    assert bg.count("chrome.tabs.create") == 1 and bg.count("loop();") == 2                       # نفس التبويب الواحد، وما بتبدأ حلقة الاستوديو
    m = re.search(r"async function quickStart.*?\nasync function quickCancel", bg, re.S)
    assert m, "quickStart غايبة"
    body = m.group(0)
    assert "setControl(" not in body and "loop(" not in body and "/result" not in body and "scriptPath" not in body
    assert "RUN.on" in body and "refreshConfig()" in body and "historyAdd(" in body
    ex = re.search(r"async function quickExec.*?\n}\n", bg, re.S).group(0)
    assert 'dest: "download"' in ex and "openInTab(" in ex and 'type: "run"' in ex and "res.stop" in ex and "sendDiag(" in ex
    assert "hold: true" in ex                                                                     # بعد الوقوف الفحص اليومي ما بيلمس التبويب
    assert ex.index("res.stop") < ex.index("finishDownload(")                                    # ما بنحفظ شي لو وقف
    # الاستئناف يدوي دايماً: التجربة السريعة ما بتكمّل لحالها بعد وقوف
    assert "resume()" not in ex


def test_downloads_are_confined_to_the_download_folder_via_offscreen_blob():
    bg = read("background.js")
    assert bg.count("chrome.downloads.download(") == 1 and "Zakiai/${plan.siteKey}/" in bg and "conflictAction: \"uniquify\"" in bg
    assert "saveAs: false" in bg and 'reasons: ["BLOBS"]' in bg
    m = re.search(r"filename = `([^`]+)`", bg)
    assert m and ".." not in m.group(1) and "${plan.siteKey}" in m.group(1) and "${stamp()}" in m.group(1)    # اسم الملف من عندنا مش من الموقع
    off = read("offscreen.js")
    assert 'm.target !== "offscreen"' in off and "sender.id !== chrome.runtime.id" in off
    assert "fetch(" not in off and "XMLHttpRequest" not in off and "MAX_BYTES" in off and "revokeObjectURL" in off
    assert '<script src="offscreen.js">' in read("offscreen.html") and "http" not in read("offscreen.html")
    content = read("content.js")
    assert 'dest: DEST' in content and 'msg.dest === "download"' in content


def test_quick_plan_validation_is_strict():
    bg = read("background.js")
    m = re.search(r"function quickPlan.*?\n}\n", bg, re.S).group(0)
    for needle in ("الموقع المختار ما بيدعم هالنوع", "اكتب البرومبت أول", "4000", ".slice(0, 4)", "image\\/", "MAX_REFS_BYTES", "QUICK_ASPECTS.includes", '["natural", "fast", "max"]'):
        assert needle in m, needle


def test_popup_has_the_quick_tab_history_and_keeps_all_studio_ids():
    h, j = read("popup.html"), read("popup.js")
    for i in ("qOpen", "studioNote", "toQuick"):
        assert f'id="{i}"' in h, i
    for needle in ('type: "open_site"', "noTasksMessage", "STUDIO_BLOCKED", 'showTab("quick")', "STUDIO_COUNTS[kind] !== 0"):
        assert needle in j, needle
    assert "popupTab" not in j                                                                    # دايماً بتفتح على «تجربة سريعة»
    for i in ("tabQuick", "tabStudio", "quickPane", "studioPane", "qKind", "qSite", "qBadge", "qPrompt", "qAspect", "qMode", "qRefs", "qNote", "qGo", "qCancel", "qStatus", "qHist", "qClear",
              "script", "kind", "site", "mode", "stepMode", "start", "pause", "resume", "cancel", "retry", "tasks", "selftest", "log", "siteBadge"):
        assert f'id="{i}"' in h, i
    assert "جرّب" in h and "آخر التجارب" in h and "Zakiai ← اسم الموقع" in h
    for needle in ('type: "quick"', 'type: "quick_cancel"', 'type: "clear_history"', 'type: "show_download"', "qRenderHistory", "esc(r.prompt)", "esc(r.reason)", "esc(r.file)", "8 * 1024 * 1024"):
        assert needle in j, needle
    assert "chrome.downloads" not in j                                                            # التنزيل بالـ background بس
    assert "AI Studio" in j and "Agent" in j                                                       # ملاحظات المواقع
    # ما في innerHTML بنص خام من الموقع/الصفحة: كل قيمة بتمرّ بـ esc
    for m in re.finditer(r"\$\{(r\.\w+)\}", j):
        assert False, m.group(0)


def test_options_has_the_flow_project_field_with_strict_validation():
    h, j, bg = read("options.html"), read("options.js"), read("background.js")
    assert 'id="flowProject"' in h and "flowProject" in j
    rx = "flow\\\\.google\\\\.com\\\\/project\\\\/[0-9a-f-]{36}"
    assert rx in j or "flow\\.google\\.com\\/project\\/[0-9a-f-]{36}" in j
    assert "FLOW_PROJECT_RX.test(" in bg and "async function urlFor" in bg and bg.count("await urlFor(") == 4     # التشغيل العادي والتجربة السريعة والفحص الذاتي وفتح الموقع بس


# ───────────────────────── الخادم: تحقق الإعداد وتقارير diag ─────────────────────────
def test_server_validation_accepts_the_new_fields_and_rejects_bad_ones():
    import copy
    base = copy.deepcopy(ext_config.DEFAULTS["sites"]["flow"])
    ext_config.validate_site("flow", base)
    steps = base["kinds"]["image"]["steps"]

    def bad(mutate, msg):
        s = copy.deepcopy(base)
        mutate(s["kinds"]["image"])
        with pytest.raises(ext_config.ExtConfigError, match=msg):
            ext_config.validate_site("flow", s)

    bad(lambda k: k["steps"].append({"do": "type", "sel": ["textarea"], "text": "x", "if": "pressed"}), "if")
    bad(lambda k: k["steps"].append({"do": "click", "sel": ["a"], "if": "sometimes"}), "if")
    bad(lambda k: k["steps"].append({"do": "click", "sel": ["a"], "via": "paste"}), "via")
    bad(lambda k: k["steps"].append({"do": "attach", "sel": ["a"], "via": "fly"}), "via")
    bad(lambda k: k["steps"].append({"do": "click", "sel": ["a"], "needs": "money"}), "needs")
    bad(lambda k: k["steps"].append({"do": "click", "sel": ["a"], "waitMs": 5}), "waitMs")
    bad(lambda k: k["steps"].append({"do": "click", "sel": ['button[aria-label="Delete project"]']}), "حذف أو شراء")
    bad(lambda k: k["steps"].append({"do": "click", "sel": ["button::contains(Upgrade)"]}), "حذف أو شراء")
    bad(lambda k: k["result"].update(reveal=["button[aria-label=\"Remove\"]"]), "حذف أو شراء")
    bad(lambda k: k["result"].update(bogus=1), "result")
    assert any(s.get("needs") == "refs" for s in steps) and any(s.get("if") == "unpressed" for s in steps)
    # reveal صالح
    fm = copy.deepcopy(ext_config.DEFAULTS["sites"]["flowmusic"])
    fm["kinds"]["music"]["result"]["reveal"] = ['button[aria-label*="Play" i]']
    ext_config.validate_site("flowmusic", fm)


@pytest.fixture
def client(env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from web import routes_ext
    import ext_bridge
    app = FastAPI()
    app.include_router(routes_ext.router)
    return TestClient(app), {"X-VP-Ext-Token": ext_bridge.token()}


DIAG = {"host": "flow.google.com", "path": "/project/:id", "composers": [{"t": "div", "aria": "What do you want to create?"}],
        "buttons": [{"t": "button", "aria": "Start generation", "disabled": True}], "fileInputs": [], "media": [], "dialogs": [], "captchaVisible": False, "evil": "x"}


def test_diag_endpoint_stores_trimmed_reports_newest_first_and_needs_token(client):
    c, h = client
    body = {"site": "flow", "kind": "image", "code": "unknown_page", "reason": "ما لقيت العنصر المطلوب", "step": "step9:click", "diag": DIAG}
    assert c.post("/api/ext/diag", json=body).status_code == 401                                   # بلا توكن
    assert c.post("/api/ext/diag", json=body, headers=h).status_code == 200
    assert c.post("/api/ext/diag", json={**body, "site": "flowmusic", "kind": "music", "code": "timeout"}, headers=h).status_code == 200
    items = c.get("/api/ext/diag").json()["items"]
    assert [i["site"] for i in items] == ["flowmusic", "flow"] and items[1]["code"] == "unknown_page" and "evil" not in items[1]["diag"]
    assert items[1]["diag"]["buttons"][0]["aria"] == "Start generation" and items[1]["at"]
    for bad in ({**body, "site": "bing"}, {**body, "kind": "pdf"}, {**body, "diag": "x"}):
        assert c.post("/api/ext/diag", json=bad, headers=h).status_code == 409
    assert (config.LIBRARY_DIR / "ext" / "diag.json").exists()


def test_diag_keeps_only_the_last_thirty_and_trims_oversized_reports(client):
    c, h = client
    big = {**DIAG, "buttons": [{"t": "button", "aria": "b" * 50, "text": "t" * 30} for _ in range(900)]}
    r = c.post("/api/ext/diag", json={"site": "flow", "kind": "image", "code": "timeout", "reason": "r", "step": "s", "diag": big}, headers=h)
    assert r.status_code == 200
    rec = c.get("/api/ext/diag").json()["items"][0]
    assert len(json.dumps(rec["diag"], ensure_ascii=False).encode()) <= ext_config.DIAG_MAX_BYTES and 0 < len(rec["diag"]["buttons"]) < 900
    for i in range(35):
        ext_config.record_diag("flow", "image", "timeout", f"n{i}", "s", DIAG)
    assert len(ext_config.diag_results(100)) == ext_config.DIAG_MAX and ext_config.diag_results(1)[0]["reason"] == "n34"


def test_diag_read_is_local_only(client):
    c, _h = client
    from fastapi.testclient import TestClient
    remote = TestClient(c.app, client=("8.8.8.8", 5000))
    assert remote.get("/api/ext/diag").status_code == 403


def test_stale_stored_config_older_than_the_bundled_one_is_ignored():
    """المالك عنده إعداد مخزّن بالإضافة من نسخة قديمة (عنوان Flow القديم): بنتجاهله لحد ما الخادم يجدّده."""
    for name in ("background.js", "popup.js"):
        src = read(name)
        assert "A.DEFAULT_CONFIG.version" in src and "adapterConfig.version" in src, name
