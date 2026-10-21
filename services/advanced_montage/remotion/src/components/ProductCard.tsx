import React from 'react';
import {ARABIC_TEXT_STYLE, BRAND} from '../lib/brand';
import {useEnter, usePulse} from '../lib/anim';
import {splitPrice} from '../lib/rtl';
import type {Overlay} from '../lib/types';
import {CardShell} from './CardShell';
import {EightStar, StarDivider} from './Ornaments';

// بطاقة المنتج والسعر: نص ثابت (ما في تقطيع حروف ولا letterSpacing)، الأرقام لاتينية، السعر داخل isolate
export const ProductCard: React.FC<{overlay: Overlay}> = ({overlay}) => {
  const {name = '', price = '', currency = ''} = overlay.content;
  const w = overlay.layout.box.w;
  const priceIn = useEnter(10, {damping: 11, stiffness: 140});
  const pulse = usePulse(40);
  const {whole, frac} = splitPrice(price);
  const nameSize = name.length <= 12 ? 108 : name.length <= 22 ? 88 : 70;

  return (
    <CardShell overlay={overlay}>
      <div
        style={{
          ...ARABIC_TEXT_STYLE,
          width: w,
          boxSizing: 'border-box',
          padding: '64px 48px 60px',
          borderRadius: 52,
          background: 'linear-gradient(165deg, rgba(29,18,64,0.95), rgba(23,42,107,0.93))',
          border: `4px solid ${BRAND.gold}`,
          boxShadow: `0 30px 80px rgba(0,0,0,0.55), 0 0 ${40 + 30 * pulse}px rgba(245,197,66,${0.18 + 0.2 * pulse})`,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 26,
          position: 'relative',
        }}
      >
        <div style={{position: 'absolute', top: -38, display: 'flex'}}>
          <div style={{background: BRAND.night, borderRadius: 40, padding: 8}}>
            <EightStar size={52} color={BRAND.gold} rotate={pulse * 22} />
          </div>
        </div>
        <div
          style={{
            fontSize: nameSize,
            fontWeight: 700,
            lineHeight: 1.25,
            color: BRAND.gold,
            textAlign: 'center',
            textWrap: 'balance',
            textShadow: '0 4px 18px rgba(0,0,0,0.5)',
          }}
        >
          {name}
        </div>
        <StarDivider width={w - 200} />
        <div
          style={{
            display: 'flex',
            flexDirection: 'row',
            alignItems: 'baseline',
            justifyContent: 'center',
            gap: 22,
            opacity: Math.min(1, priceIn * 1.5),
            transform: `scale(${0.7 + 0.3 * priceIn})`,
          }}
        >
          <span style={{unicodeBidi: 'isolate', direction: 'ltr', fontSize: 210, fontWeight: 700, lineHeight: 1, color: BRAND.white}}>
            {whole}
            {frac ? <span style={{fontSize: 120}}>{frac}</span> : null}
          </span>
          {currency ? (
            <span style={{unicodeBidi: 'isolate', fontSize: 78, fontWeight: 600, color: BRAND.turquoise}}>{currency}</span>
          ) : null}
        </div>
      </div>
    </CardShell>
  );
};
