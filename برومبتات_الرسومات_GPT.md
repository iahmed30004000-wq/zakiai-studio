# برومبتات الرسومات لـ GPT — هوية «ليالي الشرق»

**الاستخدام:** ابعت برومبت الأسلوب (١) أول شي بمحادثة جديدة، وبعدين باقي البرومبتات بنفس المحادثة، فبتطلع كل الصور بنفس الأسلوب.
**الحفظ:** كل صورة باسم الملف المكتوب، بمجلد `web/static/img/art/` (C:\Users\LOQ\Pictures\المشروع\web\static\img\art\). إذا رجعت بخلفية بدل الشفافة ابعتها متل ما هي، والخلفية بتنشال بالأداة.
**ممنوع:** نص أو حروف أو أرقام جوّا الصور (النماذج بتغلط بالعربي؛ النصوص كلها بتنحط بالكود). ممنوع وجوه بشرية وشعارات أي شركة أو لعبة حقيقية.

## ١. برومبت الأسلوب (أول واحد)
```
You are my art director for a Middle-Eastern "night bazaar" game-like UI. Keep ONE consistent visual style for every image I ask for in this chat:
- Flat vector illustration with bold clean shapes, thick 3px-style outlines in deep indigo (#120a2a), subtle grain, no photorealism, no 3D render.
- Palette only: deep night indigo #120a2a, royal purple #3a1440, sunset orange #ff7a45, sunset pink #ff4f9a, gold #f5c542, lapis blue #1f4fbf, turquoise #1fd1a5, warm cream #f6efe1.
- Motifs: eight-pointed Islamic star (girih), mihrab arches, lanterns, crescent, geometric tiles, arabesque.
- Mood: cinematic, adventurous, premium, like a mission screen in an open-world game, but respectful and Islamic-art inspired. No people's faces. No logos of any real brand or game.
- ABSOLUTELY NO text, letters or numbers inside any image.
- Unless I say otherwise: transparent background, PNG, centered subject, generous empty margin around it.
Reply "ready" only.
```

## ٢. الشعار — `logo.png` (1024×1024)
```
A logo mark for a video-ad studio: a bold eight-pointed Islamic star in gold with a small play-button triangle in its center, sitting inside a mihrab arch shape. Thick gold outline, lapis blue inner fill, turquoise tiny accents, sunset orange glow behind the star. Square 1024x1024, transparent background, no text.
```

## ٣. أيقونات المراحل السبعة — `stage-1.png` … `stage-7.png` (512×512)
```
Icon 1 of 7, "Product": a golden gift-box / perfume bottle sitting on a small ornate tile with a tiny crescent above. 512x512, transparent background.
Icon 2 of 7, "Idea": a glowing oil lantern with an eight-pointed star light inside. 512x512, transparent background.
Icon 3 of 7, "Script": an unrolled scroll with abstract lines (no readable letters) and a golden feather pen. 512x512, transparent background.
Icon 4 of 7, "Character and voice": a stylized golden microphone with sound waves shaped like arabesque curves, plus an empty round portrait medallion (no face). 512x512, transparent background.
Icon 5 of 7, "Images": an ornate picture frame in the shape of a mihrab arch with a small sun and mountains inside. 512x512, transparent background.
Icon 6 of 7, "Motion": a film clapperboard with a swirl of golden sparkles and a small flying carpet. 512x512, transparent background.
Icon 7 of 7, "Launch": a rocket made of golden geometric tiles launching over a tiny skyline with a minaret silhouette. 512x512, transparent background.
```

## ٤. الشاشات الفاضية — `empty-products.png` و`empty-characters.png` و`empty-sounds.png` (800×600)
```
Empty-state illustration "no products yet": an open empty wooden market crate with a golden star glowing inside, a few floating sparkles, a lantern hanging beside it. 800x600, transparent background.
Empty-state illustration "no characters yet": a row of three empty ornate arch niches with a spotlight on the middle one, a small golden "plus" star shape floating in front. No people. 800x600, transparent background.
Empty-state illustration "no sounds yet": an oud (Arabic lute) leaning on a cushion with musical notes floating up as small stars and crescents. 800x600, transparent background.
```

## ٥. شاشة الترحيب — `welcome.jpg` (1920×1080، بدون شفافية)
```
Wide cinematic key-art for a "mission control" home screen: a night-to-sunset sky (indigo at top, orange and pink at the horizon), a skyline of domes and minarets in silhouette, a giant faint eight-pointed star shape in the sky like a moon, floating lanterns, a winding path of golden light leading to the horizon. Leave the left third of the image calm and darker so text can sit on it. No text, no people. 1920x1080 landscape, not transparent.
```

## ٦. شاشة التحميل — `loading.png` (512×512)
```
A single golden eight-pointed star made of rotating geometric layers, shown as a clean loader emblem with a soft turquoise glow, centered, 512x512, transparent background.
```

## ملاحظات
- الألوان ثابتة بكل البرومبتات عشان الصور تركب مع الموقع.
- الصور اللي بتولّدها بحسابك إلك حسب شروط OpenAI.
- بدون الصور الموقع بيشتغل ببدائل مرسومة بالكود، بس بتكون أبسط.
