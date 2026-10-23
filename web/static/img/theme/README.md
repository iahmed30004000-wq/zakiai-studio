# صور الثيم «نجمة وطريق» — `web/static/img/theme/`

صور حقيقية بحقوق مفحوصة: ويكيميديا (CC0 و CC BY، بلا BY-SA) و Unsplash. أسماء المصوّرين والروابط بـ `credits.json`
(هو اللي بتقراه صفحة «حقوق الصور» بالموقع) و `CREDITS.md` (نفس المعلومات للقراءة). **لازم يضلّوا مع الصور.**

كل فتحة صورة إلها **بديل مرسوم** (سماء غروب + أفق مدينة + نقش كيريه)، فإذا صورة انحذفت أو ما تحمّلت، ما بيبيّن شي مكسور.

## الأسماء وأماكن الاستعمال

| الملف | `data-img` | المتغير بـ `ornament.css` | وين |
|---|---|---|---|
| `hero-home.webp` | `home` (ثيم الليل) | `--img-hero-home` | بطل الرئيسية |
| `hero-day.webp` | `home` (ثيم النهار، تلقائياً) | `--img-hero-day` | بطل الرئيسية بالنهار |
| `home-night.webp` | `home-night` | `--img-home-night` | بانوراما ليلية (شاشة التحميل وصفحة الدخول) |
| `mission.webp` | `mission` | `--img-mission` | رأس شاشة المهمة |
| `library.webp` | `library` | `--img-library` | رأس المكتبات |
| `products.webp` | `products` | `--img-products` | رف المنتجات |
| `sounds.webp` | `sounds` | `--img-sounds` | رف الأصوات (ولوحة بشاشة التحميل) |
| `pattern.webp` | `pattern` | `--img-pattern` | الأنماط |
| `factory.webp` | `factory` | `--img-factory` | رأس المصنع |
| `performance.webp` | `performance` | `--img-performance` | رأس الأداء |
| `tour.webp` | `tour` | `--img-tour` | بطاقة بداية الجولة |
| `tiles.webp` | `tiles` | `--img-tiles` | الادعاءات الممنوعة (زخرفة) |
| `petra-night.webp` | — | `--img-petra-night` | لوحة بشاشة التحميل |

الاستعمال:

```html
<section class="hero" data-img="library">…</section>        <!-- بطل بصورة -->
<div class="img-slot" data-img="products" style="height:8rem"></div>  <!-- فتحة صورة عامة -->
```

## المواصفات لأي صورة جديدة

- **الصيغة:** WebP. **المقاس:** عرض 1600 بكسل أو أقل. **الحجم:** أقل من 250 كيلوبايت.
- **التكوين:** الجزء التحتاني بيتغطّى بأفق مدينة مرسوم وظل غامق (عشان يبيّن العنوان الأبيض)، فالمهم يكون بالنص والفوق.
- **الألوان:** غروب أو ليل. الموقع بيحط فوقها طبقة غروب خفيفة (`--hero-tint`) عشان تنسجم.
- **الحقوق:** سطر بـ `credits.json` (الملف، شو فيها، المصوّر، الرخصة ورابطها، المصدر، شو عدّلنا) وبنفس الوقت بـ `CREDITS.md`.
- **ممنوع:** صور أو شعارات من ألعاب أو أفلام، أسماء شركات، صور BY-SA أو NC، أو أي صورة بلا ترخيص واضح للاستخدام التجاري.

`tests/test_phase7_look.py` بيفحص إن كل صورة إلها سطر حقوق، وإن تباين الألوان 4.5 على الأقل للثيمين.

## إضافة فتحة جديدة

1. حط الصورة هون (مثلاً `characters.webp`) وسجّل حقوقها بـ `credits.json` و`CREDITS.md`.
2. بـ `ornament.css` ضيف: `--img-characters: url("/img/theme/characters.webp");`
3. وضيف: `.hero[data-img="characters"] { --hero-img: var(--img-characters); }`
   (و`.img-slot[data-img="characters"] { --slot-img: var(--img-characters); }` إذا بدك ياها كبطاقة).

## ثيم «ساحل النيون»

صوره بمجلد `neon/` بنفس أسماء الفتحات (hero-home، library، factory…) وبنفس القواعد (WebP، أقل من 250 KB، حقوقها بـ `credits.json` بمفتاح `neon/<اسم>.webp`، وبـ `neon/CREDITS.md`). `ornament.css` بيبدّلها لما `data-theme="neon"`. ملفات `neon-coast.*` من صنع المالك (ChatGPT). ممنوع: أي لقطة أو اسم أو شعار من لعبة.
