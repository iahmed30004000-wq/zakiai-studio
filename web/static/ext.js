/* ext.js — الإضافة متعددة المواقع (جانب الواجهة من ext_contract.md):
   أدوات مشتركة لمحطات 4 و7 و9 (لوحة الإضافة بـ production.js) + مكتبة الآهات (ahat.js) + شاشة «الإضافة».
   الواجهة بتحكي مع نقاط §2 المحلية بس (بلا توكن). أي نص جاي من الخادم بيمرّ بـ esc(). */
"use strict";

/* ───────── أسماء ───────── */
const EXT_SITES = {
  gemini: "جيميناي", chatgpt: "شات جي بي تي", aistudio: "إيه آي ستوديو (Google)",
  flow: "فلو (Flow)", flowmusic: "فلو ميوزك (Flow Music)", elevenlabs: "إيليفن لابز (ElevenLabs)",
};
/* الافتراضي بالعقد §1 — بنستخدمه فقط لو الخادم ما رجّع sites */
const EXT_SITE_KINDS = {
  elevenlabs: ["voice", "ahat"], chatgpt: ["image"], gemini: ["image"], aistudio: ["image"],
  flow: ["video", "image"], flowmusic: ["music"],
};
const EXT_KINDS = { voice: "صوت مشهد", image: "صورة لقطة", video: "تحريك لقطة", ahat: "آهة", music: "موسيقى" };
const EXT_CMD = { idle: "خاملة", run: "شغّالة", pause: "متوقفة مؤقتاً", stop: "متوقفة" };

const EXT_SPEEDS = {
  natural: "الإضافة بتتصرف مثل الإنسان: بتكتب بالتدريج وبتستنى بين الخطوات. هاي أقل سرعة وأقل خطر على حسابك، وهي الموصى فيها.",
  fast: "أسرع: كتابة وانتظار أقصر. الموقع ممكن يحس إنه أتمتة، فاحتمال إيقاف الحساب أعلى من «طبيعي».",
  max: "أقصى: بتلصق النص دفعة وحدة وبأقل انتظار. هذا أعلى خطر إن الموقع يوقف حسابك. لا تستخدمه على حسابك الأساسي.",
};

/* ليش وقفت الإضافة — كلها وقوف كامل، وما في استئناف تلقائي */
const EXT_STOPS = {
  verification: "ظهر تحقق (كابتشا أو «أنت مش روبوت»)",
  unusual_activity: "الموقع لاحظ نشاط غير عادي",
  limit: "وصلت لحد الاستخدام",
  refused: "الموقع رفض الطلب (سياسة المحتوى)",
  login_required: "الموقع طلب تسجيل دخول",
  unknown_page: "الصفحة مش مثل المتوقع (ما انلقى عنصر لازم)",
};
const EXT_STEPS = {
  start: "البداية", attach: "رفع المراجع", type: "كتابة البرومبت", click: "الضغط على زر", wait: "انتظار",
  generating: "انتظار التوليد", download: "التنزيل", upload: "الرفع للاستوديو", stop: "الوقوف",
};
const EXT_REQ_STATUS = {
  pending: ["بانتظار الإضافة", "warn"], queued: ["بانتظار الإضافة", "warn"],
  running: ["قيد التوليد", "info"], in_progress: ["قيد التوليد", "info"],
  done: ["وصل للمكتبة · بانتظار سمعك", "ok"], failed: ["فشل", "danger"], error: ["فشل", "danger"],
  stopped: ["واقف", "danger"],
};

const extSite = (id) => EXT_SITES[id] || id || "—";
const extKind = (k) => EXT_KINDS[k] || k || "—";

/* حالة مشتركة: مسودات تعديل البرومبت (ما بتضيع لما اللوحة تتحدّث) */
const EXT = { draft: {}, tasks: {}, prev: {} };

/* ───────── مواقع كل نوع ───────── */
function extSiteKinds(sites, id) {
  const k = sites && sites[id] ? sites[id].kinds : null;
  if (Array.isArray(k)) return k;
  if (k && typeof k === "object") return Object.keys(k);
  return EXT_SITE_KINDS[id] || [];
}
/* المواقع اللي بتخدم نوع معيّن: [{id, label, verified}] */
function extSitesFor(kind, sites) {
  const ids = [...new Set([...Object.keys(EXT_SITES), ...Object.keys(sites || {})])];
  return ids.filter((id) => extSiteKinds(sites, id).includes(kind)).map((id) => ({
    id, label: (sites && sites[id] && sites[id].label && !EXT_SITES[id]) ? sites[id].label : extSite(id),
    verified: !!(sites && sites[id] && sites[id].verified),
  }));
}
const extVerifiedTag = (v) => (v ? `<span class="tag ok">مجرّب</span>` : `<span class="tag warn">غير مجرّب</span>`);

/* ───────── المهام الممكن اختيارها (only): من الخط الزمني — task_id حسب العقد §1 ───────── */
async function extTaskList(file, kind, force = false) {
  const key = `${file}|${kind}`, hit = EXT.tasks[key];
  if (!force && hit && Date.now() - hit.at < 60000) return hit.list;
  const r = await soft(`/api/studio/${enc(file)}/timeline`);
  const list = [];
  if (r.data && r.data.timeline) {
    r.data.timeline.scenes.forEach((sc) => {
      if (kind === "voice") list.push({ id: `scene_${sc.n}`, label: `مشهد ${sc.n}${sc.function ? " · " + sc.function : ""}` });
      else (sc.shots || []).forEach((sh) => list.push({ id: sh.id, label: `${sh.id} · مشهد ${sc.n}` }));
    });
  }
  EXT.tasks[key] = { at: Date.now(), list };
  return list;
}

/* ───────── مكان الوقوف ───────── */
function extPlaceText(c) {
  const p = c.position || {};
  const parts = [];
  const id = p.task_id || p.shot_id;
  if (id) parts.push(`${/^scene_/.test(id) ? "مشهد" : /^req_/.test(id) ? "طلب" : "لقطة"} ${id}`);
  if (p.step) parts.push("خطوة: " + (EXT_STEPS[p.step] || p.step));
  if (c.site) parts.push("الموقع: " + extSite(c.site));
  return parts.join(" · ");
}

/* ───────── إعادة مهمة مع تعديل البرومبت (POST /ext/retry) ───────── */
function extRetryModal(file, kind, taskId, defPrompt, after) {
  const key = `${file}|${kind}|${taskId}`;
  const cur = key in EXT.draft ? EXT.draft[key] : (defPrompt || "");
  openModal(`<h2>أعد المهمة ${esc(taskId)}</h2>
    <p class="hint">بتنعمل مهمة جديدة للإضافة (${esc(extKind(kind))}) حتى لو لإلها خيارات كفاية. عدّل البرومبت إذا بدك — الجديد بيستبدل القديم لهالمهمة بس. إذا ما عدّلت شي بيضل القديم.</p>
    <label class="zk-field"><span class="zk-field__label">البرومبت</span>
      <textarea class="zk-textarea" id="extMdText" rows="6" maxlength="3000">${esc(cur)}</textarea></label>
    <div class="row end"><button class="zk-btn zk-btn--ghost" id="extMdCancel" type="button">إلغاء</button>
      <button class="zk-btn zk-btn--primary" id="extMdGo" type="button">أعد المهمة</button></div>
    <div id="extMdStatus" class="status"></div>`);
  $("#extMdText").addEventListener("input", (e) => { EXT.draft[key] = e.target.value; });
  $("#extMdCancel").addEventListener("click", closeModal);
  $("#extMdGo").addEventListener("click", async (ev) => {
    const btn = ev.currentTarget, text = $("#extMdText").value.trim();
    btn.disabled = true;
    try {
      await extRetry(file, kind, taskId, text && text !== (defPrompt || "").trim() ? text : "");
      delete EXT.draft[key];
      closeModal();
      toast("انطلبت إعادة المهمة", "ok");
      if (after) after();
    } catch (e) { setStatus($("#extMdStatus"), e.message, "err"); btn.disabled = false; }
  });
}
function extRetry(file, kind, taskId, prompt) {
  const body = { task_id: taskId, kind };
  if (prompt) body.prompt = prompt;
  return api(`/api/studio/${enc(file)}/ext/retry`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

/* ───────── طلبات الآهات والموسيقى (للمكتبة وللمحطات) ───────── */
function extReqRow(r, deletable) {
  const [lbl, cls] = EXT_REQ_STATUS[r.status] || [r.status || "—", ""];
  return `<div class="reqrow" data-req="${esc(r.id)}">
    <div class="row between">
      <span><span class="tag ${r.kind === "music" ? "info" : "brand"}">${esc(extKind(r.kind))}</span> <b>${esc(r.name || r.id)}</b></span>
      <span class="tag ${cls}">${esc(lbl)}</span></div>
    <p class="reqtext">${esc(r.prompt || "")}</p>
    <p class="hint">${r.mood ? `المزاج: ${esc(r.mood_label || (typeof AH !== "undefined" && AH.moods && AH.moods[r.mood]) || r.mood)} · ` : ""}${r.seconds ? `${esc(r.seconds)}ث · ` : ""}${r.created_at ? `<span class="ltr">${esc(fmtDate(r.created_at))}</span>` : ""}</p>
    ${r.error || r.reason ? `<p class="status err">${esc(r.error || r.reason)}</p>` : ""}
    ${r.status === "done" ? `<p class="hint">دخل مكتبة الآهات <b>غير معتمد</b> — اسمعه واعتمده بنفسك من القائمة تحت.</p>` : ""}
    ${deletable ? `<div class="row"><button class="zk-btn zk-btn--danger sm" data-delreq="${esc(r.id)}" type="button">${zkIcon("delete")} احذف الطلب</button></div>` : ""}
  </div>`;
}
function extReqList(requests, deletable) {
  const list = (requests || []).filter((r) => r.kind === "ahat" || r.kind === "music");
  return list.length ? list.map((r) => extReqRow(r, deletable)).join("") : `<p class="empty">ما في طلبات لهالسيناريو.</p>`;
}
async function extDeleteRequest(file, id) {
  return api(`/api/studio/${enc(file)}/ext/requests/${enc(id)}`, { method: "DELETE" });
}

/* ───────── شاشة «الإضافة» ───────── */
const EXTP = { file: "" };

VIEWS.extension = { async enter() { await drawExtPage(); } };

async function extPageFile() {
  if (typeof PRD !== "undefined" && PRD.file) return PRD.file;
  const r = await soft("/api/scripts");
  return r.data && r.data.length ? r.data[0].file : "";
}

function extInstallSteps() {
  return `<ol class="inst">
    <li><b>نزّل وفكّ الضغط:</b> نزّل الملف من الزر فوق، وفكّ ضغطه لمجلد ثابت (مثلاً على سطح المكتب). لا تحذف المجلد ولا تنقله بعدين، لأن كروم بيقرأ الإضافة منه.</li>
    <li><b>ركّبها بكروم بوضع المطوّر:</b> افتح <code>chrome://extensions</code> ← شغّل مفتاح «وضع المطوّر» (Developer mode) من فوق ← اضغط «تحميل إضافة غير مضغوطة» (Load unpacked) ← اختار المجلد اللي فكيت ضغطه.</li>
  </ol>
  <p class="hint">وبعد التركيب: افتح خيارات الإضافة والصق توكن الاقتران (تحت). لتحديث الإضافة لاحقاً: نزّل النسخة الجديدة، بدّل محتوى نفس المجلد، وبعدين اضغط زر التحديث على كرت الإضافة بصفحة <code>chrome://extensions</code>.</p>`;
}

function extCountsHtml(d) {
  if (!d.kinds) return "";
  return `<div class="tags">${Object.keys(EXT_KINDS).map((k) =>
    `<span class="tag ${d.kinds[k] ? "warn" : "idle"}">${esc(extKind(k))}: ${esc(d.kinds[k] || 0)}</span>`).join("")}</div>`;
}

function extSelftestTable(results, sites) {
  const key = (s, k) => `${s}|${k}`;
  const byKey = new Map((results || []).map((r) => [key(r.site, r.kind), r]));
  const rows = [];
  const seen = new Set();
  const ids = [...new Set([...Object.keys(EXT_SITES), ...Object.keys(sites || {}), ...(results || []).map((r) => r.site)])];
  ids.forEach((id) => {
    const kinds = [...new Set([...extSiteKinds(sites, id), ...(results || []).filter((r) => r.site === id).map((r) => r.kind)])];
    kinds.forEach((k) => { rows.push([id, k]); seen.add(key(id, k)); });
  });
  if (!rows.length) return `<p class="empty">ما في نتائج فحص بعد.</p>`;
  return `<div class="scroll-x"><table class="tbl stack">
    <thead><tr><th>الموقع</th><th>النوع</th><th>الحالة</th><th>آخر فحص</th><th>إصدار المحوّل</th><th>التفاصيل</th></tr></thead>
    <tbody>${rows.map(([id, k]) => {
      const r = byKey.get(key(id, k)), verified = !!(sites && sites[id] && sites[id].verified);
      const st = !r ? `<span class="tag idle">ما انفحص بعد</span>` : r.ok ? `<span class="tag ok">سليم</span>` : `<span class="tag danger">فشل</span>`;
      const ver = (r && r.adapter_version != null) ? r.adapter_version : (sites && sites[id] ? sites[id].adapter_version : null);
      const miss = r && !r.ok && (r.missing || []).length
        ? `ما انلقى: ${(r.missing || []).map((m) => `<code>${esc(m)}</code>`).join(" ")}` : (r && r.ok ? "كل العناصر موجودة" : "—");
      return `<tr class="${r && !r.ok ? "gap" : ""}">
        <td data-label="الموقع"><b>${esc(extSite(id))}</b> ${extVerifiedTag(verified)}</td>
        <td data-label="النوع">${esc(extKind(k))}</td>
        <td data-label="الحالة">${st}</td>
        <td data-label="آخر فحص">${r && r.checked_at ? `<span class="ltr">${esc(fmtDate(r.checked_at))}</span>` : "—"}</td>
        <td data-label="إصدار المحوّل" class="num">${ver != null ? esc(ver) : "—"}</td>
        <td data-label="التفاصيل"><span class="selfmiss">${miss}</span></td></tr>`;
    }).join("")}</tbody></table></div>`;
}

function extSitesPreview(sites) {
  const ids = [...new Set([...Object.keys(EXT_SITES), ...Object.keys(sites || {})])];
  return `<div class="sitegrid">${ids.map((id) => {
    const s = (sites && sites[id]) || {};
    const kinds = extSiteKinds(sites, id);
    const hostsHtml = (s.hosts || []).map((h) => `<code>${esc(h)}</code>`).join(" ");
    return `<div class="sitecard">
      <div class="row between"><b>${esc(s.label && !EXT_SITES[id] ? s.label : extSite(id))}</b>${extVerifiedTag(!!s.verified)}</div>
      <div class="tags">${kinds.map((k) => `<span class="tag">${esc(extKind(k))}</span>`).join("") || `<span class="hint">—</span>`}</div>
      <p class="hint">إصدار المحوّل: <b class="num">${s.adapter_version != null ? esc(s.adapter_version) : "—"}</b></p>
      ${hostsHtml ? `<p class="hint">العنوان: ${hostsHtml}</p>` : ""}
      ${s.newUrl ? `<p class="hint">صفحة البداية: <code>${esc(s.newUrl)}</code></p>` : ""}
    </div>`;
  }).join("")}</div>`;
}

async function drawExtPage() {
  const box = $("#extBody");
  if (!box) return;
  const file = await extPageFile();
  EXTP.file = file;
  const [st, st2, tk] = await Promise.all([
    file ? soft(`/api/studio/${enc(file)}/ext/status`) : Promise.resolve({ data: null, err: null }),
    soft("/api/ext/selftest"),
    soft("/api/ext/token"),
  ]);
  const d = st.data, sites = d && d.sites ? d.sites : null, c = d ? d.control : null;
  box.innerHTML = `
    <div class="notice warn"><b>تنبيه مهم:</b> أتمتة هالمواقع بتخالف شروط استخدامها وممكن يوقفوا حسابك. الأحسن تستعمل <b>حساب ثانوي</b> مو حسابك الأساسي، وتخلّي السرعة <b>«طبيعي»</b>.
      الإضافة بتوقف كلياً عند أي تحقق أو كابتشا أو طلب دخول، وما بتتجاوز أي حماية، وما بتقرأ ولا بتكتب كلمات سر. وبعد الوقوف ما في استئناف تلقائي — إنت بتضغط «كمّل» بنفسك بعد ما تحل الموضوع.</div>

    <div class="panel"><h3>تنزيل وتركيب الإضافة</h3>
      <div class="row">
        <a class="zk-btn zk-btn--primary" id="extDl" href="/api/ext/download" download>${zkIcon("download")} نزّل الإضافة (zip)</a>
        <button class="zk-btn zk-btn--ghost sm" id="extVerBtn" type="button">اعرف رقم الإصدار</button>
        <span class="hint" id="extVer"></span>
      </div>
      ${extInstallSteps()}
    </div>

    <div class="panel"><h3>توكن الاقتران</h3>
      <p class="hint">الصق هالتوكن بخيارات الإضافة عشان تتعرّف على استوديوك. بيتخزّن بمخزن أسرار ويندوز عندنا، مش بأي ملف. هو للاستخدام على نفس جهازك بس.</p>
      ${extTokenHtml(tk.data)}
    </div>

    <div class="panel"><h3>وضع الإضافة هلأ</h3>
      ${d ? `<div class="row"><span class="tag ${c.command === "stop" && c.stop_code ? "danger" : c.command === "run" ? "ok" : ""}">${c.command === "stop" && c.stop_code ? "واقفة" : esc(EXT_CMD[c.command] || c.command)}</span>
          <span class="hint">السيناريو: <code>${esc(file)}</code></span></div>
        <p class="hint">المهام المعلّقة لكل نوع:</p>${extCountsHtml(d) || `<span class="hint">بالطابور ${esc(d.queue)} لقطة</span>`}
        ${c.command === "stop" && c.stop_code ? `<div class="notice danger"><b>وقفت:</b> ${esc(c.stop_reason || EXT_STOPS[c.stop_code] || c.stop_code)}${extPlaceText(c) ? `<br><span class="hint">${esc(extPlaceText(c))}</span>` : ""}</div>` : ""}
        <p class="hint">التحكم (سرعة، لقطة لقطة، إعادة...) من محطات الإنتاج 4 و7 و9، وطلبات الآهات والموسيقى من <a href="#/library/sounds">مكتبة الآهات</a>.</p>`
      : `<p class="empty">${file ? esc(st.err ? st.err.message : "حالة الإضافة غير متاحة") : "اختر سيناريو من شاشة «الإنتاج» لتظهر حالة الإضافة."}</p>`}
    </div>

    <div class="panel"><div class="row between"><h3>نتائج الفحص الذاتي</h3>
        <button class="zk-btn zk-btn--ghost sm" id="extStRefresh" type="button">${zkIcon("refresh")} حدّث</button></div>
      <p class="hint">الإضافة بتفحص كل موقع لحالها (يومياً) وبتبعت النتيجة هون: هل لقت صندوق الكتابة والأزرار اللي بتحتاجها؟ <b>«غير مجرّب»</b> يعني إعدادات الموقع لسا ما انجرّبت على الحقيقة — جرّب لقطة وحدة قبل ما تعتمد عليها.</p>
      ${st2.data ? extSelftestTable(st2.data.results, sites) : `<div>${errBox(st2.err)}</div>`}
    </div>

    <div class="panel"><h3>إعداد المواقع (للقراءة فقط)</h3>
      <p class="hint">المواقع اللي بتشتغل عليها الإضافة وشو بتنتج من كل واحد. تعديل الإعداد بيصير من الخادم مش من هون.</p>
      ${sites ? extSitesPreview(sites) : `<p class="empty">${d ? "الخادم ما رجّع قائمة المواقع." : "تظهر بعد ما تختار سيناريو."}</p>`}
    </div>`;

  extBindToken(box, () => drawExtPage());
  $("#extStRefresh").addEventListener("click", () => drawExtPage());
  $("#extVerBtn").addEventListener("click", extProbeVersion);
}

/* رقم الإصدار: من اسم الملف بترويسة /ext/download (zakiai-extension-<ver>.zip) — بنقرأ الترويسة بس ونلغي الجسم */
async function extProbeVersion(ev) {
  const out = $("#extVer"), btn = ev.currentTarget;
  if (MOCK) { setStatus(out, ""); out.textContent = "الإصدار 1.2.0 (محاكاة)"; return; }
  btn.disabled = true; out.textContent = "بيقرأ…";
  try {
    const r = await fetch("/api/ext/download");
    const m = /extension-([^"';\s]+?)\.zip/i.exec(r.headers.get("content-disposition") || "");
    if (r.body && r.body.cancel) r.body.cancel().catch(() => {});
    out.textContent = r.ok ? (m ? `الإصدار ${m[1]}` : "الإصدار ما انذكر بالترويسة — بيظهر باسم الملف بعد التنزيل") : `خطأ ${r.status}`;
  } catch { out.textContent = "تعذّر الاتصال بالسيرفر"; }
  finally { btn.disabled = false; }
}
