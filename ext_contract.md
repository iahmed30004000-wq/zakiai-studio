# عقد الإضافة متعددة المواقع (v2، إضافة v0.3) — مرجع لكل من الخادم والإضافة والواجهة

الهدف: الإضافة بتنتج ٥ أنواع شغل (صوت · صور · تحريك · آهات · موسيقى) من ٦ مواقع، وكل نتيجة بترجع لمكانها بالاستوديو.
الموجود وما بيتكسر: `ext_bridge.py` و`web/routes_ext.py` و`extension/*` و`tests/test_studio_extension.py` (468 اختبار ناجح بالمشروع كله).
**توافق للخلف:** نقاط `/ext/queue` و`/ext/result` (بـ shot_id و site) بتضل شغّالة وبنفس السلوك (صور).

## ١. الأنواع والمواقع والمحطات

| kind | المعنى | محطة | مين بيطلبه | task_id |
|---|---|---|---|---|
| `voice` | صوت مشهد | ٤ | تلقائي: مشهد فيه voiceover وما إله ملف من الإضافة لنفس النص | `scene_<n>` |
| `image` | صورة لقطة | ٧ | تلقائي (الموجود) | `<shot_id>` |
| `video` | تحريك لقطة | ٩ | تلقائي: لقطة صورتها النهائية معتمدة وما إلها مرشّح حركة | `<shot_id>` |
| `ahat` | آهة/مؤثر | مكتبة | المالك بيطلب من الواجهة | `req_<id>` |
| `music` | موسيقى | مكتبة | المالك بيطلب من الواجهة | `req_<id>` |

المواقع (`SITES`): `gemini` · `chatgpt` · `aistudio` · `flow` · `flowmusic` · `elevenlabs`.

الافتراضي (`kinds` لكل موقع):
- `elevenlabs`: voice, ahat
- `chatgpt`: image
- `gemini`: image
- `aistudio`: image
- `flow`: video, image
- `flowmusic`: music

مؤجّل بقرار صريح: «تعديل جزء من الصورة» (يحتاج رسم قناع بالواجهة) واستنساخ الصوت (يحتاج ملف موافقة صاحب الصوت) — لا تبنوهم ولا تحطّوا لهم أزرار.

## ٢. نقاط الخادم (كلها بـ `/api`)

بتوكن `X-VP-Ext-Token` (للإضافة) — تحت `/studio/{filename}/ext/`:
- `GET tasks?kind=<kind>` → `{kind, tasks:[Task], control}`. يحترم `control.only` (قائمة task_id) لو موجودة.
- `GET asset/{task_id}/{index}` → ملف مرجع (صور المراجع للـ image، والصورة النهائية للـ video index 0).
- `POST result` (multipart): `file`, `task_id`, `kind` (افتراضي image), `site`, و`shot_id` اختياري (توافق قديم؛ لو task_id غايب بنستخدمه) → `{done, ...}`.
- `GET queue`, `GET control`, `POST log`, `POST stop`, `GET ref/{shot_id}/{index}` — الموجودة، بدون تغيير.
بتوكن — عام:
- `GET /ext/config` → إعداد المحوّلات المدموج (راجع §٤).
- `POST /ext/diag` `{site, kind?, code, reason, step, diag}` → تقرير بنية الصفحة (تسميات أزرار وصناديق كتابة ووسائط، **بدون نص محتوى ولا قيم حقول**) من الإضافة عند وقوف `unknown_page`/`timeout`/`download_failed`. بنخزّن آخر 30 بـ `library/ext/diag.json` (وبنقصّ أي تقرير أكبر من ~24KB).
- `GET /ext/version` → `{latest, download_url}` (latest من extension/manifest.json).
- `POST /ext/selftest` `{site, kind?, ok, adapter_version, missing:[str]}` → يخزّن.
محلي فقط (للواجهة، بدون توكن، 127.0.0.1):
- `PUT /ext/config` جسم `{sites:{<site>:{...جزئي...}}}` دمج عميق + رفع `version`.
- `GET /ext/selftest` → `{results:[{site, kind, ok, adapter_version, missing, checked_at}]}`.
- `GET /ext/diag?limit=10` → آخر تقارير الوقوف (الأحدث أول) — بيستعملها المطوّر لمعايرة المحدّدات بدون ما المالك يصوّر شاشة.
- `GET /ext/download` → zip للإضافة `vidpattern-extension-<ver>.zip`.
- `GET /studio/{f}/ext/status` (موجود) ← بيزيد: `kinds:{voice:n,image:n,video:n,ahat:n,music:n}` (عدد المهام المعلّقة لكل نوع)، `requests:[...]`، `sites:{<site>:{kinds,verified,adapter_version}}`.
- `POST /studio/{f}/ext/control` (موجود) ← بيقبل كمان: `kind`, `step_mode` (`all`|`one_by_one`), `only` (قائمة task_id أو null).
- `POST /studio/{f}/ext/requests` `{kind: ahat|music, prompt, name, mood, seconds}` → طلب آهة/موسيقى.
- `DELETE /studio/{f}/ext/requests/{id}`.
- `POST /studio/{f}/ext/retry` `{task_id, kind, prompt?}` → يعيد لقطة/مشهد: بيجبر مهمة جديدة (want=1) ويستبدل البرومبت لو انبعت.

## ٣. شكل المهمة Task
```json
{"task_id":"s1c1","kind":"video","scene":1,"shot_id":"s1c1","prompt":"...","text":"نص الصوت (voice بس)",
 "emotion_tag":"[دافئ]", "seconds":3.4, "want":1,
 "refs":[{"index":0,"name":"final.png"}], "site_hint":"flow", "retry":false}
```
- voice: `prompt` = (وسم الإحساس + نص المشهد) للصق بالموقع؛ `text` = النص الصافي؛ `seconds` = المدة المخطّطة.
- video: `seconds` = مدة اللقطة بالثواني؛ `refs[0]` = صورتها النهائية المعتمدة.
- music: الخادم **دايماً** بيضيف للبرومبت «instrumental, no vocals, no lyrics — بلا غناء ولا كلام». ahat: برومبت المالك + «clean, isolated sound effect, no music».
- `only` بالـ control بيقصر القائمة على task_ids محدّدة؛ `retry` بيدخل المهمة حتى لو عندها خيارات كفاية.

## ٤. إعداد المحوّلات (يُخدَّم من الخادم، والإضافة بتخزّنه بـ storage وبتحدّثه كل تشغيل)
```json
{"version":2,
 "sites":{"flow":{
   "label":"Flow","adapter_version":2,"verified":false,
   "hosts":["flow.google.com"],"newUrl":"https://flow.google.com/",
   "kinds":{"image":{
      "url":"https://flow.google.com/",
      "steps":[
        {"do":"click","sel":["button.agent-mode-chip"],"if":"pressed","optional":true,"waitMs":3000},
        {"do":"click","sel":["button[aria-label=\"Settings trigger\"]"],"optional":true,"waitMs":3000},
        {"do":"click","sel":["button[role=\"radio\"]::contains({aspect})"],"if":"unpressed","optional":true,"waitMs":2000},
        {"do":"click","sel":["button[aria-label=\"Add ingredients to the prompt box\"]"],"needs":"refs","optional":true},
        {"do":"attach","sel":["input[type=\"file\"]"],"optional":true},
        {"do":"type","sel":["div.ProseMirror[role=\"textbox\"]"],"text":"{prompt}"},
        {"do":"click","sel":["button[aria-label=\"Start generation\"]"],"optional":false}],
      "busy":["[role=progressbar]"],
      "result":{"type":"image","sel":["img[alt*=\"Tile displaying\" i]"],"download":[]},
      "timeoutSec":300}},
   "selftest":{"composer":["div.ProseMirror[role=\"textbox\"]"]}}}}
```
- `steps[].do` ∈ `click` | `type` | `attach` | `wait` (`ms`). `sel` = قائمة بدائل (أول واحد موجود). `optional:true` = لو ما لقيناه نكمّل بعد انتظار قصير (5 ثواني افتراضي، أو `waitMs` 200–30000). `text` قالب فيه `{prompt}` و`{seconds}`.
- **حقول الخطوات (v0.3):**
  - `needs:"refs"` — الخطوة بتتنفّذ بس لو في صور مرجعية (مثلاً فتح حوار الإرفاق).
  - `if:"pressed"|"unpressed"` (للنقر بس) — ينضغط بس لو حالة الزر (aria-pressed/checked/selected أو كلاس `mat-button-toggle-checked`) مختلفة عن المطلوب. مثال: إطفاء شريحة «Agent» بـ Flow، وتثبيت النسبة وعدد النتائج.
  - `via:"input"|"drop"|"paste"` (للإرفاق بس) — `input` بيعبّي حقل الملفات، `drop`/`paste` بيحاكوا إسقاط/لصق الصور على العنصر (Gemini: `paste` على صندوق الكتابة).
  - `waitMs` — أقصى انتظار لظهور عنصر الخطوة.
- **محدّدات (v0.3):** `CSS::contains(نص)` = عناصر بتطابق الـ CSS ونصها الظاهر (أو aria-label) فيه النص بدون حساسية حروف (مثال: `button[role="radio"]::contains(9:16)`)، و`{aspect}` داخل المحدّد بيتبدّل وقت التشغيل بنسبة الفريم (الافتراضي `9:16`، والمهمة بتقدر تحمل `aspect`).
- **ممنوع بأي محدّد:** كلمات السر/الرموز، وأي فعل مدمّر أو مالي (delete/remove/trash/purchase/buy/checkout/upgrade/subscribe/logout/sign out/billing/حذف/شراء/ترقية/اشتراك/خروج) — الإضافة بتولّد بس.
- `result.type` ∈ `image` | `audio` | `video`. الإضافة بتاخد **أحدث عنصر جديد** (مش موجود قبل الإرسال) وبتنزّله `fetch(credentials:include)` وبترفعه.
- `result.reveal` (اختياري) — أزرار «شغّل/افتح» بتنضغط (4 دورات بلا نتيجة، حتى 3 مرات) لو النتيجة ما ظهرت بعد ما خلص التوليد (مثلاً أغنية بـ Flow Music لازم تنشغّل عشان يطلع ملفها).
- أي `sel` ما انلقى (غير optional) ← وقوف `unknown_page` (ومعه تقرير `diag`) بدون تخمين.
- `verified:false` (الافتراضي لكل المواقع لحد ما تنجح تجربة حقيقية) ← الواجهة والـ popup بيعرضوا «غير مجرّب».
- الخادم هو المصدر: `ext_config.py` فيه `DEFAULTS` (6 مواقع)، وملف تعديلات `library/ext/adapters.json` بيندمج فوقه. `adapters.js` فيه نسخة مضمّنة **لازم تطابق DEFAULTS** (`tests/test_ext_quick.py` بيفحص التطابق)، وإعداد مخزّن بالإضافة بنسخة أقدم من المضمّن بيتجاهَل.
- **عناوين حقيقية (قراءة بصفحات المواقع الحقيقية 2026-10-21):** Flow = `flow.google.com` (العنوان القديم `labs.google/fx/tools/flow` بيحوّل ومش مسموح)، وFlow Music = `www.flowmusic.app` (و`flowmusic.app`).
- Flow: شريط الإدخال فيه وضع «Agent» (وكيل بيسأل تأكيد قبل التوليد) ووضع مباشر؛ الإضافة بتشتغل بالمباشر وبتثبّت النوع والنسبة وعدد النتائج x1 (حماية الرصيد). مشروع Flow ثابت (اختياري) بخيارات الإضافة (`flowProject`).

## ٤ب. التجربة السريعة (إضافة v0.3)
- بنافذة الإضافة تبويب «تجربة سريعة»: موقع + نوع + برومبت (+ صور مرجعية حتى 4) ← «جرّب». ما بتحتاج استوديو ولا سيناريو ولا توكن.
- نفس المحرّك والتبويب الواحد وقواعد الوقوف. النتيجة بتنحفظ بمجلد التنزيلات: `VidPattern/<الموقع>/<التاريخ-الوقت>.<امتداد>` (اسم الملف من عندنا مش من الموقع)، وبتتسجّل بسجل «آخر التجارب» (آخر 20).
- التنزيل: الصفحة بتبعت قطع الملف (`dest:"download"`) للـ background ← صفحة `offscreen.html` بتجمّعها Blob ← `chrome.downloads.download` (مرة وحدة، بالـ background بس).
- صلاحيات إضافية (v0.3): `downloads` و`offscreen`.

## ٥. قواعد ثابتة (ما بتتفاوض)
- تبويب واحد، حساب واحد. ولا قراءة لحقول كلمات السر، ولا كتابة كلمات سر، ولا تجاوز كابتشا/تحقق/حد استخدام/نشاط غير عادي/طلب دخول: وقوف كامل + حفظ المكان + تنبيه.
- الإضافة بتحكي بس مع `localhost:8000` ومع مواقع التوليد المعلنة بـ host_permissions. ممنوع أي عنوان تاني.
- صلاحيات manifest: `storage` · `notifications` · `alarms` (للفحص اليومي) · `downloads` + `offscreen` (حفظ نتيجة «التجربة السريعة» بمجلد التنزيلات) — لا غير.
- الصوت من الإضافة: التوقيت بعد التنزيل بـ stt (`stt.transcribe`)، وإذا فشل أو ما في مفتاح ← `tts.estimate_words` مع `timing_source:"estimated"` ظاهر.
- الموسيقى دايماً بلا غناء. الآهات/الموسيقى بتدخل المكتبة **غير معتمدة** وبتنتظر سمع المالك.
- لغة الرسائل للمالك: عربية بسيطة شامية، بلا مصطلحات غير مشروحة.
- مفاتيح/توكنات: ما بتنكتب بأي ملف ولا بتنطبع بالسجل.
