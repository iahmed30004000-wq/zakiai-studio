# صور الهوية «ليالي الشرق» — `web/static/img/theme/`

صور مجانية مرخّصة (Unsplash). أسماء المصوّرين وروابط الصور بـ `CREDITS.md` بنفس المجلد — **لازم يضل موجود مع الصور**.

كل فتحة صورة إلها **بديل مرسوم** (سماء غروب + أفق مدينة + نقش كيريه)، فإذا صورة انحذفت أو ما تحمّلت، ما بيبيّن شي مكسور.

## الأسماء وأماكن الاستعمال

| الملف | `data-img` | المتغير بـ `ornament.css` | وين |
|---|---|---|---|
| `hero-home.jpg` | `home` (ثيم الليل) | `--img-hero-home` | بطل الرئيسية |
| `hero-day.jpg` | `home` (ثيم النهار، تلقائياً) | `--img-hero-day` | بطل الرئيسية بالنهار |
| `home-night.jpg` | `home-night` | `--img-home-night` | بديل ليلي للرئيسية |
| `mission.jpg` | `mission` | `--img-mission` | رأس شاشة المهمة |
| `library.jpg` | `library` | `--img-library` | رأس المكتبات |
| `products.jpg` | `products` | `--img-products` | رف المنتجات |
| `sounds.jpg` | `sounds` | `--img-sounds` | رف الأصوات والآهات |
| `pattern.jpg` | `pattern` | `--img-pattern` | صفحة تفاصيل النمط |
| `factory.jpg` | `factory` | `--img-factory` | رأس المصنع |
| `performance.jpg` | `performance` | `--img-performance` | رأس الأداء |
| `tour.jpg` | `tour` | `--img-tour` | بطاقة بداية الجولة |
| `tiles.jpg` | `tiles` | `--img-tiles` | زخرفة (بطاقة أو خلفية فاتحة) — كبيرة (1.6 ميغا)، استعملها بقلّة |

الاستعمال:

```html
<section class="hero" data-img="library">…</section>        <!-- بطل بصورة -->
<div class="img-slot" data-img="products" style="height:8rem"></div>  <!-- فتحة صورة عامة -->
```

## المواصفات لأي صورة جديدة

- **الصيغة:** JPG. **المقاس:** عرض حوالي 1920 بكسل، نسبة عريضة. **الحجم:** يفضّل أقل من 450 كيلوبايت.
- **التكوين:** الجزء التحتاني بيتغطّى بأفق مدينة مرسوم وظل غامق (عشان يبيّن العنوان الأبيض)، فالمهم يكون بالنص والفوق.
- **الألوان:** غروب أو ليل. الموقع بيحط فوقها طبقة غروب خفيفة (`--hero-tint`) عشان تنسجم.
- **ممنوع:** صور أو شعارات GTA الرسمية، أو أي صورة بلا ترخيص واضح للاستخدام التجاري.

## ثيم «ساحل النيون» — `neon/`

ثيم تالت (ليل ساحلي بنيون، طابع بس) بصوره الخاصة بمجلد `neon/`، ونفس أسماء `data-img` السابقة: بيبدّلها `ornament.css` تلقائياً لما الثيم يكون `neon`
(متغيرات `--img-*` معرّفة من جديد تحت `[data-theme="neon"]`)، فما في حاجة لأي تعديل بالصفحات.

| الملف بـ `neon/` | وين |
|---|---|
| `home.jpg` · `mission.jpg` · `library.jpg` · `factory.jpg` · `performance.jpg` · `products.jpg` · `sounds.jpg` · `pattern.jpg` | أبطال الصفحات (نفس أسماء الثيمين التانيين) — صور Unsplash، حقوقها بـ `neon/CREDITS.md` |
| `neon-coast.door.webp` / `neon-coast.door-tall.webp` | خلفية صفحة الدخول (عريضة، وطولية للجوال) — صور المالك من الـ OMS |
| `neon-coast.strip.webp` | شريط 5:1 (محفوظ للترويسة والفواصل) — صور المالك من الـ OMS |

القواعد: بلا اسم GTA ولا شعارات Rockstar ولا لقطات من اللعبة ولا خط Pricedown. الشكل (حدود سودا، ظلال حادة، خط Bangers/Lalezar) كله بـ CSS بآخر `ornament.css`.
تباين الألوان (4.5 على الأقل لكل أزواج النص) بيفحصه `tests/test_phase7_look.py` للثيمات التلاتة.

## إضافة فتحة جديدة

1. حط الصورة هون (مثلاً `characters.jpg`) وسجّل حقوقها بـ `CREDITS.md`.
2. بـ `ornament.css` ضيف: `--img-characters: url("/img/theme/characters.jpg");`
3. وضيف: `.hero[data-img="characters"] { --hero-img: var(--img-characters); }`
   (و`.img-slot[data-img="characters"] { --slot-img: var(--img-characters); }` إذا بدك ياها كبطاقة).
