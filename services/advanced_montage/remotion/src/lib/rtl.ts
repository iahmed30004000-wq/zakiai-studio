// أرقام لاتينية دائماً (0-9) — حتى لو وصلت أرقام هندية بالغلط نحوّلها
const AR_DIGITS = '٠١٢٣٤٥٦٧٨٩';
const FA_DIGITS = '۰۱۲۳۴۵۶۷۸۹';

export const latinDigits = (s: string): string =>
  s
    .replace(/[٠-٩]/g, (d) => String(AR_DIGITS.indexOf(d)))
    .replace(/[۰-۹]/g, (d) => String(FA_DIGITS.indexOf(d)))
    .replace(/٫/g, '.')
    .replace(/٬/g, ',');

// «19.9» → {whole:'19', frac:'.9'} لعرض السعر بحجم كبير
export const splitPrice = (price: string): {whole: string; frac: string} => {
  const t = latinDigits(price).trim();
  const m = t.match(/^(\d[\d,]*)([.,]\d+)?$/);
  if (!m) {
    return {whole: t, frac: ''};
  }
  return {whole: m[1], frac: m[2] ?? ''};
};
