# عقد إعادة بناء الواجهة «ليالي الشرق» — مرجع مشترك لثلاث وكلاء

المرجع الكامل للفكرة: `خطة_إعادة_بناء_الموقع.md` (الأقسام ٢–٥) و`معاينة_الشكل.html` (الشكل «أ»).
قرارات المالك: الشكل «أ — ليالي الشرق» · صور حقيقية مرخّصة (لاحقاً بعد موافقته على القائمة) · **استبدال مباشر** (ما في واجهة قديمة جنب الجديدة).

## مبادئ ثابتة
- **ما في تغيير على الخادم ولا على الـ API.** كل منطق الشاشات الموجود (app.js, studio.js, production.js, settings.js, perf.js, characters.js, productref.js, models.js, ext.js, ahat.js) بيضل شغّال؛ منعيد **تركيبه** مش كتابته. أي حذف منطق = فقط لو مكرّر فعلاً (خطوة الاستوديو 5 «الصوت والصور»).
- عربي شامي بسيط، RTL، `esc()` لكل نص من الخادم، أرقام غربية بالتعليقات، بلا مفاتيح بأي ملف.
- يشتغل على 360px بلا تمرير أفقي. لوحة المفاتيح والتركيز ظاهرين. احترام `prefers-reduced-motion`.
- الاختبارات الموجودة (tests/test_phase7_static.py، test_ui_ext.py وغيرها) لازم تضل ناجحة؛ لو اختبار بيفحص بنية قديمة انحذفت عن قصد (مثلاً نص تبويب بالقائمة) عدّله بأقل تغيير واذكره بالتقرير. **ممنوع** تضعيف أي اختبار أمان/هروب نصوص.
- رقم `?v=` بكل الروابط بيرتفع لـ 30.

## الهيكل الجديد (المسارات)
| المسار | الاسم بالقائمة | المحتوى | مالك |
|---|---|---|---|
| `#/home` (الافتراضي) | ◆ الرئيسية | خريطة المهمات + «بانتظارك» + حالة الطرق + ملخص المكتبة + الاستهلاك | S |
| `#/mission/<file>?stage=N` و `#/mission/new?stage=1` | ✦ المهمة | المراحل السبعة | M |
| `#/library/<tab>` tabs: `patterns` `products` `characters` `sounds` | ❖ المكتبات | المكتبة (الأنماط+التوزيع+المراجعة+الحصاد) · المنتجات · الشخصيات (+مراجع المنتج) · الآهات والموسيقى | S |
| `#/factory/<tab>` tabs: `api` `local` `extension` | ⚙ المصنع | API (من الإعدادات: الاتصالات والموديلات + الصوت والصور + المفاتيح) · النماذج المحلية (models) · الإضافة | S |
| `#/performance` | ★ الأداء | كما هو | S |
| `#/settings` | (زر ترس بالترويسة) | باقي الإعدادات | S |
| `#/pattern/<id>` | (بلا عنصر بالقائمة) | صفحة تفاصيل النمط | S |

**تحويل المسارات القديمة** (S): `pipeline→home`، `library→library/patterns`، `products/<f>→library/products/<f>`، `characters→library/characters`، `product-ref→library/characters/...` (أو يبقى مسار تفاصيل)، `ahat→library/sounds`، `models→factory/local`، `extension→factory/extension`، `studio→mission/new?stage=2`، `production/<f>?s=n→mission/<f>?stage=<مرحلة المحطة>`.

**تركيب الشاشات الموجودة داخل الحاويات الجديدة:** المسموح والمفضّل نقل عقد DOM الموجودة (`appendChild` بيحافظ على المستمعات) إلى حاوية التبويب/المرحلة الجديدة ثم نداء `VIEWS.<قديم>.enter(p)` بمعامل مسار مُكيَّف. الأقسام القديمة `<section class="view">` بتضل بالـ HTML كمصدر (مخفية) إذا لزم.

## المراحل السبعة (M) ← المحطات/الخطوات الموجودة
| stage | الاسم | مصدرها |
|---|---|---|
| 1 | المنتج | شاشة المنتجات (البريف + الاكتمال + المراجع البصرية) |
| 2 | الفكرة | خطوة الاستوديو 1 (اختيار المنتج + أفضل 3 أنماط) |
| 3 | السيناريو | خطوات الاستوديو 2–4 (كتابة، سيناريو ومراجعة، موافقة وتصدير) → بعد الموافقة ينشأ `<file>` وينتقل `#/mission/<file>?stage=4` |
| 4 | الشخصية والصوت | المحطات 3·4·5 |
| 5 | الصور | المحطات 6·7·8 |
| 6 | التحريك والآهات | المحطة 9 + جزء الآهات من 10 |
| 7 | المونتاج والإطلاق | المحطة 10 (المونتاج) + 11 |
- كل مرحلة فيها محطات فرعية بتنعرض كتبويبات صغيرة داخلها (من `production.js`).
- **شريط سفلي ثابت:** «← رجوع» · «التالي →». «التالي» مقفول مع سبب عربي واضح وزر «ودّيني» للمكان الناقص (من حالات المحطات `studio_state`). لما مرحلة تكتمل: لافتة «المرحلة نجحت ✓» (`Ornament.passed()` من V، أو class `mission-passed`).
- محطات المرحلة الحالية بيظهروا كمان بالشريط الجانبي (بديل `#railStations`).

## واجهة الدليل (S بيبنيها، M وغيرهم بيستخدموها) — `guide.js` بيعرّف `window.Guide`
```js
Guide.stagePanel(hostEl, { what, why, example, tips?:[] })   // لوحة «دليل المرحلة» قابلة للطي (حالتها بـ localStorage مع try/catch)
Guide.term(key)            // يرجّع HTML لعلامة «؟» جنب مصطلح؛ القاموس GLOSSARY بـ guide.js (نمط، بريف، مرشّح، محطة، بوابة المدة، الإضافة، الخطّاف، اللقطة، الشخصية، المونتاج…)
Guide.next()               // «شو بعمل هلأ؟»: يحسب الخطوة الجاية (من /api/scripts + حالات المحطات) ويرجّع {text, hash}
Guide.tour(force?)         // جولة أول مرة (5 محطات) — بتشتغل تلقائياً أول زيارة فقط
Guide.palette()            // Ctrl+K: بحث وتنقّل (شاشات، منتجات، سيناريوهات، أنماط)
```
زر «شو بعمل هلأ؟» وزر «؟ الجولة» دايماً بالترويسة (S).

## الشكل (V) — «ليالي الشرق»
- ثيمين: `data-theme="night"` (افتراضي) و`data-theme="day"` (نهار، فاتح). مبدّل الثيم بالترويسة بيتبادل بينهم (S بيعدّل THEMES بـ boot.js لهالاتنين).
- `theme.css`: قيم `--vp-*` للثيمين (بدل الربط بـ zk)، مع إبقاء أسماء `--vp-*` كما هي عشان كل الشاشات تتلوّن تلقائياً. وكمان ضبط `--zk-*` الأساسية لنفس القيم عشان مكوّنات zaki-ui تتبع.
- لوحة الألوان: سماء ليل (#120a2a→#3a1440)، ذهبي #f5c542، لازوردي #1f4fbf، فيروزي #1fd1a5، غروب (برتقالي #ff7a45 → زهري #ff4f9a) للعناوين والبطاقات البطلة فقط. النص العادي هادئ وواضح (تباين AA).
- `ornament.css` (جديد): خطوط بـ `@import` من Google Fonts (Lalezar للعناوين الكبيرة، Reem Kufi للعناوين، IBM Plex Sans Arabic للنص) مع بدائل محلية؛ نقش النجمة الثمانية (SVG data-URI) كخلفية خفيفة؛ بطاقات بقوس محراب `.arch`؛ إطار زخرفي `.frame-girih`؛ بطاقة بطل `.hero` بغروب؛ لافتة `.mission-passed`؛ نجوم الجودة `.stars`؛ شريط المراحل `.mission-steps` (done/now/locked)؛ شريط سفلي `.mission-bar`؛ لوحة الدليل `.guide-panel`؛ `.term-q`؛ لوحة البحث `.palette`؛ جولة `.tour-*`؛ انتقال صفحات سريع («شاشة تحميل») مع reduced-motion.
- فتحات صور: متغيرات `--img-hero-home`, `--img-library`, `--img-factory`, `--img-mission` بتأشّر على `/img/theme/*.jpg` مع **بديل تدرّج** لو الصورة مش موجودة (الصور لسا ما نزلت).
- `ornament.js` صغير (اختياري): `window.Ornament = { passed(el, text), stars(n) }`.
- إعادة تلوين مكوّنات style.css (أزرار، لوحات، تبويبات `.seg`، `.steps`، `.stn-tabs`، جداول، شارات) لتتماشى — بدون كسر أسماء الكلاسات.

## ملكية الملفات (ممنوع تعديل ملف غيرك)
- **V:** `theme.css`، `ornament.css` (جديد)، `ornament.js` (جديد)، `style.css`، `web/static/img/theme/` (README فقط، بلا تنزيل)، `vendor/` لا تُلمس.
- **S:** `index.html`، `boot.js`، `app.js` (فقط: VIEWS.pipeline/library/products/pattern ووصلات التنقل وroute helpers)، `home.js` (جديد)، `guide.js` (جديد)، `shell.js` (جديد إن لزم)، `settings.js` (فقط لفصل أقسام API إلى المصنع)، `characters.js`/`ahat.js`/`models.js`/`ext.js`/`perf.js` (فقط تعديلات تركيب/روابط)، mock جديدة للرئيسية، الاختبارات `tests/test_ui_shell.py`.
- **M:** `mission.js` (جديد)، `studio.js`، `production.js`، الاختبارات `tests/test_ui_mission.py`. M بيرسم داخل `#missionBody` بقسم `<section id="v-mission" class="view" data-view="mission">` (S بيضيفه بـ index.html وبيسجّل `mission.js` و`guide.js` و`home.js` و`ornament.js/css` بالترتيب: zaki-ui → app → studio → perf → settings → production → characters → productref → models → ext → ahat → guide → ornament → home → mission → boot).
- **التواصل بين الملفات عبر:** `VIEWS`، `window.Guide`، `window.Ornament`، `window.Mission = { stageOfStation(n), hash(file, stage) }` (M بيعرّفها؛ S بيستخدمها للتحويل من مسارات production القديمة ولـ Guide.next).
