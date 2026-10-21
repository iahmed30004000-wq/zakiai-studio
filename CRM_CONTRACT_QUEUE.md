# عقد الطابور ورفع المكتبة — الطرف الذي ينفّذه المالك في الـ CRM

> **عقد افتراضي صمّمه VidPattern** (مش موجود بالـ CRM بعد). هو **مكمّل** لـ `CRM_CONTRACT.md` (وكيل B1: قراءة الأداء وحقائق المنتج). نفس القواعد العامة هناك بتنطبق هون: HTTPS، `Authorization: Bearer <token>`، JSON UTF-8، بلا redirect، `5xx`/انقطاع = «أوفلاين» والجهاز بيعيد المحاولة، `4xx` = خطأ عقد.

## الفكرة

- الـ CRM **ما بينادي** VidPattern أبداً. الجهاز ممكن يكون مطفي أو نايم أو وراه جدار.
- الـ CRM بيترك الطلب بطابور بالسيرفر (حالة «بانتظار الجهاز»). VidPattern بيسحبه **كل `CRM_QUEUE_POLL_MINUTES` (افتراضي 60 دقيقة)** ولما يشتغل الجهاز (catch-up)، وبيرد بـ**مسودة**.
- **كل رد مسودة**: ما في شي بينشر إعلان ولا بيصرف فلوس. الـ CRM لازم يعرض المسودة لإنسان ويطلب موافقته قبل أي إجراء. VidPattern ما بيرسل أوامر تنفيذ، وما في بأي رد حقول `publish` / `budget` / `spend`؛ وإذا وصلت لأي سبب تجاهلها.
- **لا بيانات زبائن** بأي حمولة (طابور أو مكتبة) — لا اسم ولا هاتف ولا عنوان ولا رقم طلب.

### صلاحيات التوكن (مهم — يختلف عن توكن الأداء)

توكن الأداء بـ `CRM_CONTRACT.md` للقراءة فقط. هالمسارات بدها **كتابة محدودة**؛ نفس التوكن (أو توكن تاني بنفس المكان بمخزن ويندوز) لازم يسمح بـ 3 عمليات كتابة بس، ولا شي غيرها:

| العملية | المسار |
|---|---|
| مطالبة بطلب | `POST /api/vidpattern/queue/{id}/claim` |
| تسليم نتيجة | `POST /api/vidpattern/queue/{id}/result` |
| رفع المكتبة | `PUT /api/vidpattern/library` |

كل ما عداها (تعديل طلبات، طلبيات، زبائن، إعلانات…) لازم يبقى محجوباً عن هالتوكن.

---

## 1) قراءة الطابور — `GET /api/vidpattern/queue?status=pending`

الرد `200`:

```json
{
  "items": [
    {
      "id": "vq_01J8Y3K2",
      "type": "new_script",
      "payload": {"product_code": "kama", "pattern_id": "مكتبة_الإعلانات_125"},
      "created_at": "2026-09-29T08:15:00Z"
    },
    {
      "id": "vq_01J8Y3M9",
      "type": "best_patterns",
      "payload": {"product_code": "kama"},
      "created_at": "2026-09-29T08:20:00Z"
    },
    {
      "id": "vq_01J8Y3P4",
      "type": "extract_ad_features",
      "payload": {"url": "https://www.facebook.com/ads/library/?id=123456"},
      "created_at": "2026-09-29T08:31:00Z"
    }
  ]
}
```

- **ما بيرجع إلا** الطلبات اللي بانتظار الجهاز: `pending`، **و**`claimed` اللي انتهت مهلتها (lease) — عشان الطلب اللي التقطه الجهاز وانطفى قبل ما يرد يرجع للطابور لحاله.
- الترتيب: الأقدم أولاً. حد أقصى للرد 50 عنصر (VidPattern بيعالج 5 بالدورة كحد افتراضي؛ الباقي بالدورات الجاية).
- `id`: نص معتم ≤ 80 حرف، فريد ثابت. VidPattern بيعتبره مفتاح idempotency.
- `type` ∈ `new_script` · `extract_ad_features` · `best_patterns`. نوع تاني = VidPattern بيرد `failed` («نوع الطلب غير مدعوم»).

### الحمولة `payload` حسب النوع

| النوع | الحقول | ملاحظات |
|---|---|---|
| `new_script` | `product_code` (نص، إلزامي) · `pattern_id` (اختياري) | المنتج لازم يكون له ملف `products/*.json` عند VidPattern (بيتطابق على `product_code` أو اسم الملف). بلا `pattern_id` بيختار VidPattern النمط الأنسب. بيكتب سيناريو + دورة المراجعة. |
| `best_patterns` | `product_code` (إلزامي) | بيرجّع أفضل 3 أنماط للمنتج. |
| `extract_ad_features` | `url` (`http`/`https` إلزامي) | VidPattern بينزّل الفيديو، بيستخرج، وبيشرّح النمط. الروابط المحلية/الداخلية (`localhost`، `192.168.x.x`…) بتنرفض. **جانب أثر:** النمط بينضاف لمكتبة الجهاز. |

---

## 2) المطالبة — `POST /api/vidpattern/queue/{id}/claim`

الطلب:

```json
{"lease_seconds": 3600}
```

| الرد | المعنى | تصرّف VidPattern |
|---|---|---|
| `200 {}` | الطلب صار `claimed` مع مهلة `lease_seconds` من الآن | بيبدأ التنفيذ |
| `409` | الطلب مأخوذ بمهلة سارية من جهاز تاني، أو خلص | بيتخطّاه بدون خطأ |
| `404` / `410` | الطلب انحذف/انلغى | بيتخطّاه ويسجّله منجز محلياً |

- **مطالبة نفس الجهاز مرة تانية جائزة** (idempotent: بتجدّد المهلة). الجهاز ممكن يعيد المطالبة بعد انقطاع.
- إذا فشل الجهاز مؤقتاً، ما بيرسل شي: المهلة بتخلص والطلب بيرجع `pending` بالسيرفر تلقائياً (لهيك مهلة طويلة نسبياً: استخراج فيديو ممكن ياخد دقايق).

---

## 3) تسليم النتيجة — `POST /api/vidpattern/queue/{id}/result`

### نجاح (مسودة)

```json
{"status": "draft", "draft": { "kind": "...", "...": "..." }}
```

بالضبط مفتاحين. أشكال `draft`:

**`kind: "script"`** (للنوع `new_script`)

```json
{
  "kind": "script",
  "script_file": "kama__مكتبة_الإعلانات_125__20260929_1030.json",
  "script_id": "VP-kama-3-v1",
  "status": "reviewing",
  "product_code": "kama",
  "pattern_id": "مكتبة_الإعلانات_125",
  "title": "…",
  "hook_line": "…",
  "cta_line": "…",
  "total_duration_sec": 47,
  "scenes": [
    {"scene_number": 1, "duration_sec": 4.5, "visual": "…", "voiceover": "…", "on_screen_text": "…"}
  ]
}
```

`status` ∈ `draft` · `reviewing` · `approved` · `needs_owner` (حالة السيناريو محلياً بعد المراجعة الآلية). حتى `approved` تعني «اجتاز المراجعة الآلية» — **مش** موافقة على النشر.

**`kind: "best_patterns"`** (للنوع `best_patterns`)

```json
{
  "kind": "best_patterns",
  "product_code": "kama",
  "patterns": [
    {"pattern_id": "…", "pattern_name": "…", "fit_score": 87, "reason": "…",
     "required_adaptation": "…", "category_distance": "same", "transfer_justification": null}
  ],
  "warnings": ["خيارات محدودة"]
}
```

أقصى 3 أنماط.

**`kind: "ad_features"`** (للنوع `extract_ad_features`)

```json
{
  "kind": "ad_features",
  "url": "https://…",
  "pattern": { "pattern_id": "crm_vq_01J8Y3P4", "pattern_name": "…", "framework": "pas", "hook": {"type": "…"}, "…": "…" }
}
```

أو إذا كان النمط مكرر لنمط موجود: `{"kind":"ad_features","url":"…","duplicate":true,"note":"…"}`. حقول `pattern` هي نفس القائمة البيضاء لرفع المكتبة (القسم 4)؛ **بلا** نص التفريغ الخام ولا مخطط المشاهد.

### فشل

```json
{"status": "failed", "reason": "المنتج 'ghost' مش موجود محلياً"}
```

`reason` عربي جاهز للعرض، بلا مفاتيح ولا مسارات جهاز.

### ردود السيرفر

| الرد | المعنى | تصرّف VidPattern |
|---|---|---|
| `200 {}` | تم الحفظ (الطلب صار `draft_ready` أو `failed`) | بيسجّل الطلب منجز |
| `404` / `409` / `410` | الطلب انحسم قبل أو انحذف | بيعتبره منجز (ما في شي يعيده) |
| `5xx` / انقطاع | مؤقت | **بيحتفظ بالمسودة محلياً** وبيعيد الإرسال بالدورة الجاية بدون إعادة حساب |

### سياسة الفشل (بيعرفها الـ CRM ليعرض حالة صحيحة)

| نوع الفشل | مثال | النتيجة |
|---|---|---|
| **دائم** | نوع غير مدعوم، منتج مش موجود محلياً، رابط غير صالح/داخلي، حمولة ناقصة | `result` بحالة `failed` مباشرة |
| **مؤقت** | انقطاع مزوّد الموديل، فشل تحميل، عطل غير متوقّع | **بدون `result`**؛ الطلب بيضل «بانتظار الجهاز». بعد **3 محاولات** فاشلة بيصير `failed` مع آخر سبب |
| **حد إنفاق** | وصل الحد اليومي/الشهري للموديلات | بدون `result` وبدون عدّ محاولة؛ بيتنفّذ لما ينزل الإنفاق أو يرتفع الحد |

الـ CRM يعرض للمستخدم «بانتظار الجهاز» طول ما الطلب `pending`/`claimed` — بلا مهلة نهائية.

---

## 4) رفع المكتبة — `PUT /api/vidpattern/library`

نسخة **للقراءة فقط** من مكتبة الأنماط، عشان مركز الذكاء بالـ CRM يقراها والجهاز مطفي. بيرفعها VidPattern **بعد كل تغيير بمحتوى الحزمة** (hash) — مش كل دورة. الـ CRM بيستبدل النسخة السابقة كلياً (snapshot، مش دمج).

الطلب:

```json
{
  "schema_version": 1,
  "content_hash": "sha256 hex",
  "generated_at": "2026-09-29T09:00:00+00:00",
  "pattern_count": 132,
  "per_category": {"fragrance": 14, "skincare": 9},
  "patterns": [
    {
      "pattern_id": "مكتبة_الإعلانات_109",
      "pattern_name": "…",
      "framework": "pas",
      "framework_secondary": null,
      "one_line_summary": "…",
      "product_category": "fragrance",
      "target_audience": "…",
      "dialect_or_language": "shami",
      "dialect_sub": "…",
      "hook": {"type": "…", "duration_sec": 12.3, "mechanism": "…", "transferable_template": "…"},
      "emotional_arc": ["…"],
      "product_entry_sec": 12.3,
      "product_entry_style": "…",
      "proof_mechanism": "…",
      "objection_handled": "…",
      "cta": "…",
      "pacing": "…",
      "visual_language": "…",
      "why_it_works": "…",
      "weak_points": "…",
      "production_complexity": "…",
      "best_for": "…",
      "avoid_for": "…",
      "reusability_score": 7,
      "cluster_id": "…",
      "cluster_role": "primary",
      "source": {"duration_sec": 48.2, "views": 250000, "likes": 4100, "url": "https://…"},
      "evidence": {
        "evidence_level": "proven",
        "evidence_score": 82,
        "delivered": 240,
        "spend": 610.5,
        "cost_per_delivered": 2.54,
        "scripts": 3,
        "cost_vs_baseline": 0.81,
        "reason": "…",
        "as_of": "2026-09-28"
      }
    }
  ]
}
```

- كل الحقول بالنمط اختيارية إلا `pattern_id` (غير موجودة = ما انعرّفت بالنمط). `evidence` غايب لو ما في بيانات أداء.
- `evidence_level` ∈ `proven` · `weak` · `unproven`؛ `evidence_score` 0–100.
- **اللي ما بيرتفع أبداً** (قائمة بيضاء على جهة VidPattern، ولا تخزّنه لو وصلك): نصوص الفيديوهات الخام/التفريغ، مخطط المشاهد، اللقطات والفيديوهات والأصول، مسارات الجهاز، بيانات زبائن، أي أسرار. أي نص بالحزمة مقصوص عند 700 حرف.
- الرد `200 {}`. `413` إذا كبرت الحزمة (الحجم المتوقع < 2 ميجا لـ ~150 نمط؛ ارفع الحد لـ 5 ميجا). `5xx`/انقطاع → VidPattern بيعيد الرفع بالدورة الجاية (الـ hash ما بيتسجّل إلا بعد النجاح).
- اعرض للمستخدم `generated_at` («آخر تحديث من الجهاز») — المكتبة ممكن تكون أقدم من الواقع لو الجهاز مطفي.

---

## ملخّص ما بيحتاجه الـ CRM

1. جدول طابور: `id, type, payload(JSON), status(pending|claimed|draft_ready|failed), lease_until, claimed_at, result(JSON), created_at, decided_at`.
2. `GET` بيرجّع `pending` + `claimed` منتهية المهلة (أقدم أولاً، حد 50).
3. `claim` ذرّية (409 لو مأخوذ بمهلة سارية أو منتهي).
4. `result` بيخزّن المسودة/الفشل ويعرضها للموافقة البشرية — **بلا أي تنفيذ تلقائي**.
5. `library` بيخزّن آخر snapshot + `generated_at` للعرض.
6. توكن بصلاحيات الكتابة الثلاث أعلاه فقط.
