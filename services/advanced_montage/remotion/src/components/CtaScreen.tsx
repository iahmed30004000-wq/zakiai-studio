import React from 'react';
import {AbsoluteFill} from 'remotion';
import {ARABIC_TEXT_STYLE, BRAND} from '../lib/brand';
import {useEnter, useExit, usePulse} from '../lib/anim';
import type {Overlay} from '../lib/types';
import {Chevron, EightStar, StarPattern} from './Ornaments';

// شاشة «اطلب هلأ»: خلفية ليلية فوق اللقطة (backdrop) + زر ذهبي كبير نابض. كل النص جوّا المنطقة الآمنة.
export const CtaScreen: React.FC<{overlay: Overlay; productName?: string}> = ({overlay, productName}) => {
  const duration = overlay.end_frame - overlay.start_frame;
  const text = overlay.content.text ?? 'اطلب هلأ';
  const bg = useEnter(0, {damping: 20, stiffness: 90});
  const btn = useEnter(6, {damping: 10, stiffness: 130});
  const exit = useExit(duration, 6);
  const pulse = usePulse(30);
  const b = overlay.layout.box;
  const withBackdrop = overlay.layout.backdrop;

  return (
    <AbsoluteFill style={{opacity: exit}}>
      {withBackdrop ? (
        <AbsoluteFill
          style={{
            opacity: Math.min(1, bg) * 0.9,
            background: `radial-gradient(ellipse at 50% 38%, ${BRAND.nightSoft} 0%, ${BRAND.night} 78%)`,
          }}
        >
          <StarPattern opacity={0.1} />
        </AbsoluteFill>
      ) : null}
      <div
        style={{
          ...ARABIC_TEXT_STYLE,
          position: 'absolute',
          left: b.x,
          top: b.y,
          width: b.w,
          height: b.h,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 52,
          textAlign: 'center',
        }}
      >
        <div style={{opacity: Math.min(1, bg * 1.6), transform: `translateY(${(1 - bg) * -40}px)`}}>
          <EightStar size={120} color={BRAND.gold} rotate={pulse * 45} />
        </div>
        {productName ? (
          <div
            style={{
              fontSize: 76,
              fontWeight: 600,
              lineHeight: 1.3,
              color: BRAND.cream,
              opacity: Math.min(1, bg * 1.6),
              textWrap: 'balance',
              textShadow: '0 4px 16px rgba(0,0,0,0.5)',
            }}
          >
            {productName}
          </div>
        ) : null}
        <div
          style={{
            fontSize: 150,
            fontWeight: 700,
            lineHeight: 1.1,
            color: BRAND.night,
            padding: '34px 110px 46px',
            borderRadius: 120,
            background: `linear-gradient(180deg, #ffe08a 0%, ${BRAND.gold} 55%, ${BRAND.goldDeep} 100%)`,
            boxShadow: `0 20px 60px rgba(0,0,0,0.5), 0 0 ${40 + 60 * pulse}px rgba(245,197,66,${0.35 + 0.35 * pulse})`,
            opacity: Math.min(1, btn * 1.6),
            transform: `scale(${(0.6 + 0.4 * btn) * (1 + 0.045 * pulse)})`,
          }}
        >
          {text}
        </div>
        <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, opacity: Math.min(1, btn)}}>
          <Chevron size={92} opacity={0.35 + 0.65 * pulse} />
          <Chevron size={92} opacity={1 - 0.65 * pulse} />
        </div>
      </div>
    </AbsoluteFill>
  );
};
