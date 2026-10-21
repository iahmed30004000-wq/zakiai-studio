import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {ARABIC_TEXT_STYLE, BRAND} from '../lib/brand';
import type {CaptionLine, Style} from '../lib/types';

const FONT_SIZE = 70;

// الكلمة النشطة = آخر كلمة بدأت (بالميلي ثانية) ما لم يخلص السطر
const activeWordIndex = (line: CaptionLine, tMs: number): number => {
  let idx = -1;
  for (let i = 0; i < line.words.length; i++) {
    if (line.words[i].start_ms <= tMs) {
      idx = i;
    }
  }
  return idx;
};

const Line: React.FC<{line: CaptionLine; style: Style}> = ({line, style}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const local = frame - line.start_frame;
  const tMs = (frame * 1000) / fps;
  const active = activeWordIndex(line, tMs);

  const enter = interpolate(local, [0, 4], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const lineFrames = line.end_frame - line.start_frame;
  const exit = interpolate(local, [lineFrames - 3, lineFrames], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});

  return (
    <div
      style={{
        ...ARABIC_TEXT_STYLE,
        opacity: Math.min(enter, exit),
        transform: `translateY(${(1 - enter) * 14}px)`,
        display: 'flex',
        flexDirection: 'row', // مع direction:rtl أول كلمة بتجي عاليمين
        flexWrap: 'wrap',
        justifyContent: 'center',
        alignItems: 'baseline',
        columnGap: 18,
        rowGap: 6,
        maxWidth: style.safe_zone.rect.w,
        padding: '16px 34px 20px',
        borderRadius: 34,
        background: 'rgba(18, 10, 42, 0.58)',
        fontWeight: 700,
        fontSize: FONT_SIZE,
        lineHeight: 1.45,
        color: BRAND.white,
        textShadow: '0 3px 10px rgba(0,0,0,0.85), 0 0 3px rgba(0,0,0,0.9)',
      }}
    >
      {line.words.map((w, i) => {
        const isActive = style.highlight_word !== false && i === active;
        const startFrame = Math.round((w.start_ms * fps) / 1000);
        // نبضة خفيفة وقت بدء الكلمة (spring قصير): 1 → 1.09 → 1
        const pulse = isActive
          ? 1 + 0.09 * Math.sin(Math.min(1, spring({frame: frame - startFrame, fps, config: {damping: 14, stiffness: 220}, durationInFrames: 12})) * Math.PI)
          : 1;
        return (
          // كل كلمة كاملة بـ span واحد: ممنوع تقطيع أو تلوين حرف داخل كلمة (بيكسر الوصل)
          <span
            key={i}
            style={{
              display: 'inline-block',
              unicodeBidi: 'isolate',
              color: isActive ? style.highlight : BRAND.white,
              transform: `scale(${pulse})`,
              transformOrigin: '50% 80%',
              textShadow: isActive
                ? `0 3px 10px rgba(0,0,0,0.85), 0 0 22px ${style.highlight}66`
                : undefined,
            }}
          >
            {w.text}
          </span>
        );
      })}
    </div>
  );
};

// ترجمة كلمة بكلمة: أسطر الـ job، نص RTL عربي، بالمنطقة الآمنة (الـ 22٪ السفلية فاضية للمنصة)
export const ArabicCaptions: React.FC<{lines: CaptionLine[]; style: Style}> = ({lines, style}) => {
  const frame = useCurrentFrame();
  const line = lines.find((l) => frame >= l.start_frame && frame < l.end_frame);
  if (!line) {
    return null;
  }
  return (
    <AbsoluteFill
      style={{
        justifyContent: 'flex-end',
        alignItems: 'center',
        // أسفل الشريط فوق المنطقة الآمنة السفلية (422px) بفاصل صغير؛ شريط الترجمة ارتفاعه الأقصى band_h
        paddingBottom: style.caption.bottom_px + 12,
      }}
    >
      <Line line={line} style={style} />
    </AbsoluteFill>
  );
};
