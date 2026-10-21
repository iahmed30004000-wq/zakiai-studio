// هوية «ليالي الشرق»
export const BRAND = {
  gold: '#f5c542',
  goldDeep: '#c99a1e',
  night: '#120a2a',
  nightSoft: '#1d1240',
  lapis: '#26419b',
  lapisDeep: '#172a6b',
  turquoise: '#2fc6b8',
  cream: '#fff6dc',
  white: '#ffffff',
} as const;

export const FONT_FAMILY = '"IBM Plex Sans Arabic", "Segoe UI", Tahoma, sans-serif';

// تشكيل الحروف العربية: كل ميزات الوصل والتشكيل شغالة، وممنوع أي letterSpacing (بيكسر وصل الحروف)
export const ARABIC_TEXT_STYLE = {
  fontFamily: FONT_FAMILY,
  direction: 'rtl' as const,
  unicodeBidi: 'plaintext' as const,
  letterSpacing: 0,
  wordSpacing: 0,
  fontKerning: 'normal' as const,
  fontFeatureSettings: '"liga" 1, "calt" 1, "ccmp" 1, "locl" 1, "mark" 1, "mkmk" 1, "kern" 1',
  fontVariantLigatures: 'common-ligatures contextual',
  textRendering: 'optimizeLegibility' as const,
  WebkitFontSmoothing: 'antialiased' as const,
};
