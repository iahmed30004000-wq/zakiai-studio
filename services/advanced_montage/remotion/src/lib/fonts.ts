import {cancelRender, continueRender, delayRender, staticFile} from 'remotion';

// خطوط IBM Plex Sans Arabic (OFL) محلية بالكامل: public/fonts/*.woff2 — ولا طلب شبكة وقت الرندر.
// كل وزن له ملفين: عربي (الحروف والتشكيل) ولاتيني (الأرقام والعلامات) تحت نفس اسم العائلة.
const FAMILY = 'IBM Plex Sans Arabic';
const WEIGHTS = [400, 500, 600, 700] as const;
const RANGE_ARABIC =
  'U+0600-06FF, U+0750-077F, U+0870-088E, U+0890-0891, U+0897-08E1, U+08E3-08FF, U+200C-200E, U+2010-2011, U+204F, U+2E41, U+FB50-FDFF, U+FE70-FE74, U+FE76-FEFC';
const RANGE_LATIN =
  'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-200B, U+200F-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD';

let started: Promise<void> | null = null;

export const loadFonts = (): Promise<void> => {
  if (started) {
    return started;
  }
  const handle = delayRender('تحميل الخطوط العربية');
  const jobs: Promise<unknown>[] = [];
  for (const w of WEIGHTS) {
    for (const [script, range] of [
      ['arabic', RANGE_ARABIC],
      ['latin', RANGE_LATIN],
    ] as const) {
      const face = new FontFace(
        FAMILY,
        `url(${staticFile(`fonts/ibm-plex-sans-arabic-${w}-${script}.woff2`)}) format('woff2')`,
        {weight: String(w), style: 'normal', unicodeRange: range, display: 'block'},
      );
      jobs.push(
        face.load().then((f) => {
          (document.fonts as unknown as {add: (f: FontFace) => void}).add(f);
        }),
      );
    }
  }
  started = Promise.all(jobs)
    .then(() => document.fonts.ready)
    .then(() => {
      continueRender(handle);
    })
    .catch((err) => {
      // لو الخط ما انحمّل لازم الرندر يفشل بوضوح بدل ما يطلع بخط النظام بالسر
      cancelRender(new Error('فشل تحميل الخطوط العربية: ' + String(err)));
    });
  return started;
};
