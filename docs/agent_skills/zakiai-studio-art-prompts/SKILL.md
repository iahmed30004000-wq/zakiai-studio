---
name: zakiai-studio-art-prompts
description: Ready-to-paste ChatGPT (GPT image) prompts and the asset workflow for the owner's Zakiai Systems content studio («استوديو المحتوى» — the Arabic video-ad studio at C:\Users\LOQ\Pictures\المشروع, FastAPI + vanilla JS, الهوية «ليالي الشرق») — empty-state drawings (patterns, hooks bank, cinematic moves, activity), the login background, the logo/stage icons/welcome art — plus the rule for what is NOT asked of GPT (the «ساحل النيون» theme, back since 23/10, uses real photos + the OMS neon-coast art). Use when the owner (Ahmad / Zaki AI) asks for studio art or prompts, says «الصور جاهزة», drops GPT-generated images for the studio, wants art for a new studio screen, or whenever a studio task needs a picture. Claude cannot paint raster art and the owner says ChatGPT is the best at it, so write prompts for him instead of settling for placeholders, and deliver ALL the prompts together as ONE Word (.docx) file (his standing rule).
---

# Zakiai Studio art prompts (استوديو المحتوى)

The owner generates the pictures with ChatGPT; Claude writes the prompts, checks what comes back, converts it and wires it in. Reply to him in Arabic only (Levantine, short, non-technical, one example). Studio art is **original only**: no real brands, no game logos, no faces.

Sibling skills do the same for other projects — `daftar-art-prompts` (دفتر), `falak-art-prompts` (فلك), `zaki-image-prompts` (System 7 and the OMS). **Do not mix their palettes or art with the studio's**, and never put studio art in the OMS (no OMS repo changes without «نفّذ العمليات»).

## Where the art lives and how a missing picture behaves

All art is under `web/static/img/art/` (illustrations) and `web/static/img/theme/` (photos for the page heroes). Every slot has a **drawn fallback in code** (a faint eight-pointed star, a sunset gradient), so a missing picture never breaks a screen — the work is never blocked on art.

Empty-state art is wired by `data-art="<key>"` on `<p class="empty">`; `ornament.css` maps `data-art="x"` to `/img/art/empty-x.png`, and `ornament.js` (`artCheck`) removes the attribute when the file is missing so the star fallback shows. Adding a new empty state = a PNG named `empty-<key>.png` + one CSS line.

### Look (since 23/10): «نجمة وطريق»

The approved redesign is Islamic-inspired: navy night, gold, turquoise, sunset; 8-point stars, girih, mihrab arches, muqarnas. Ornaments are drawn in code, illustrations come from GPT. Match the existing `stage-*` and `empty-*` art (bold outlined sticker style, glowing gold and lanterns). No text, no faces, no brands in any image; people only as dark silhouettes or hands.

### Slots (state on 2026-10-23)

| Key / file | Where | Size | State |
|---|---|---|---|
| `logo.png` | header, login | 1024² | done |
| `stage-1…7.png` | mission stages | 512² | done |
| `empty-products.png`, `empty-characters.png`, `empty-sounds.png` | library empty states | 800×600 | done |
| `welcome.jpg` / `welcome-rtl.jpg` | home hero | 1920×1080 | done |
| `loading.png` | loader | 512² | done |
| `empty-patterns.png` | library → patterns (empty) | 800×600 transparent | requested again 23/10 (first sent 22/10) |
| `empty-hooks.png` | library → hooks bank (empty) | 800×600 transparent | requested again 23/10 |
| `empty-moves.png` | library → cinematic moves | 800×600 transparent | requested again 23/10 |
| `empty-activity.png` | settings → activity | 800×600 transparent | requested again 23/10 |
| `login-bg.jpg` | login page background (portrait-safe centre) | 1920×1080 | requested again 23/10 |
| `new-guided.png` | «＋ جديد» card «مهمة موجّهة»: 7 glowing stars to a finished vertical frame | 800×600 transparent | new 23/10 |
| `new-free.png` | card «مشروع حر»: hands arranging tiles on a geometric table | 800×600 transparent | new 23/10 |
| `new-quick.png` | card «شغلة سريعة»: one spark making one picture and one sound wave | 800×600 transparent | new 23/10 |
| `guide-cover.jpg` | in-site guide «دليل زاكي» cover: illuminated manuscript, lantern; right 45% calm for the title | 1600×900 | new 23/10 |
| `guide-help.png` | guide «عندي مشكلة»: lantern lighting a knotted thread being untangled | 800×600 transparent | new 23/10 |
| `mission-done.png` | «المهمة نجحت»: star medal with geometric fireworks | 1024×1024 transparent | new 23/10 |
| `factory-ready.png` | factory → studio readiness: astrolabe/gears with three lamps (API / models / extension) | 800×600 transparent | new 23/10 |
| `not-found.png` | page not found: empty mihrab archway with a compass | 800×600 transparent | new 23/10 |

## What is NOT drawn by GPT

- **The ornament** (eight-pointed stars, girih tiles, skyline) — SVG in code (`ornament.css`): it must tile, recolour per theme and stay sharp.
- **The «ساحل النيون» theme** — BACK by the owner's explicit wish on 23/10 (GTA-style night neon). Real photos from Unsplash / Wikimedia / Pexels under `web/static/img/theme/neon/` with `credits.json`, plus the OMS neon-coast art (`neon-coast.door/door-tall/strip.webp`). Never the GTA/Rockstar name, logos or game screenshots; the only display font allowed is Bangers (OFL). It is **never asked from GPT**.
- **Anything with text inside.** Arabic lettering from an image model is wrong; text is always real text in code.

## Workflow

1. **Inventory** the screens that need a picture: screen, final size, transparent or not, file name. Batches of ≤ 8.
2. **Write one prompt per picture** with the recipe below — English, one paragraph, copy-paste ready. The first item of every pack is the **style prompt** (`references/zakiai-art.json`, id `style`) — it pins the palette and the "night bazaar" look so a batch matches the existing art.
3. **Deliver ONE Word (.docx) with ALL the prompts of the request** — his standing rule. Add the new prompts to `references/zakiai-art.json` (`"pack": "new"`; old finished ones become `"base"`), then run `python scripts/build_docx.py` (writes `برومبتات_رسومات_الموقع_الجديدة.docx` into the project root; `--pack all` includes the old ones). Send it with `SendUserFile` and name the drop folder and the exact file names.
4. **When the PNGs arrive** (he says «الصور جاهزة»): open each one (Read the image) and check — no letters inside, no faces, transparent background where asked (a chequerboard "fake transparent" background is wrong), details that survive shrinking. Send back the exact prompt tweak for any that fail.
5. **Process and wire in**: copy to `web/static/img/art/<name>`; for a new empty state add `.empty[data-art="<key>"]::before { background-image: url("/img/art/empty-<key>.png"); }` to `ornament.css` and `data-art="<key>"` to the `<p class="empty">`; **bump every `?v=` in `index.html` and `login.html` together** (they must stay identical); run the static tests; look at it in the browser (mock mode `/?mock=1`).

## Prompt recipe

`Empty-state illustration "<what is missing>": <one sentence of the scene, using the studio motifs: eight-pointed star, mihrab arch, lantern, crescent, tiles, arabesque>. No people. 800x600, transparent background.`

- The negative list lives in the style prompt (no text/letters/numbers, no faces, no brands) — repeat "No text" in a prompt only if the scene tends to attract writing (books, signs, screens, ledgers).
- **One ChatGPT conversation per pack**, style prompt first, then each prompt in the same chat.
- Ask 4:3 (800×600), 1:1 or 16:9 — those come back reliably. Crop anything else yourself.
- Palette (never invent others): navy night `#0d2140`, indigo `#120a2a`, purple `#3a1440`, sunset orange `#ff7a45`, pink `#ff4f9a`, gold `#f5c542`, lapis `#1f4fbf`, turquoise `#1fd1a5`, cream `#f6efe1`.
- Slots with text-prone objects (books, scrolls, screens, ledgers) say "no writing" inside the prompt itself.

## What was sent, and when

- **2026-10-21** — the original pack (style, logo, 7 stage icons, 3 empty states, welcome, loading): `برومبتات_الرسومات_GPT.md` in the project (kept for reference; this skill is now the source of truth). All delivered and in `img/art/`.
- **2026-10-22** — pack of 6 prompts (style + empty-patterns, empty-hooks, empty-moves, empty-activity, login-bg). Never came back, nothing wired in.
- **2026-10-23** — pack of 14 items (style + the 5 above resent + 8 new: new-guided, new-free, new-quick, guide-cover, guide-help, mission-done, factory-ready, not-found): `برومبتات_رسومات_الموقع_الجديدة.docx` in the project root (not git-ignored; tracked files of this kind exist), built by `python scripts/build_docx.py --pack new`. One ChatGPT chat for the whole pack. Nothing wired in yet.
