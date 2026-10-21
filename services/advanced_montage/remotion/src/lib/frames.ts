// ms → إطار. نفس صيغة الـ adapter (captions.frame_of): تقريب لأقرب إطار بحساب صحيح، فما في فجوة ولا تداخل.
export const frameOf = (ms: number, fps = 30): number => Math.floor((Math.round(ms) * fps + 500) / 1000);

export const clamp = (v: number, a: number, b: number): number => Math.min(b, Math.max(a, v));
