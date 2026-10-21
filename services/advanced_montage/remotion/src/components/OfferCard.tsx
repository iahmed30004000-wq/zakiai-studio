import React from 'react';
import {ARABIC_TEXT_STYLE, BRAND} from '../lib/brand';
import {useEnter, usePulse} from '../lib/anim';
import {latinDigits} from '../lib/rtl';
import type {Overlay} from '../lib/types';
import {CardShell} from './CardShell';
import {ShieldCheck, StarDivider} from './Ornaments';

const sizeFor = (s: string, big: number, mid: number, small: number): number =>
  s.length <= 16 ? big : s.length <= 28 ? mid : small;

// بطاقة العرض: عرض (شارة كبيرة) + ضمان (أيقونة درع) + ندرة اختيارية. الحقل الفاضي ما بينرسم.
export const OfferCard: React.FC<{overlay: Overlay}> = ({overlay}) => {
  const c = overlay.content;
  const offer = latinDigits(c.offer ?? '');
  const guarantee = latinDigits(c.guarantee ?? '');
  const deadline = latinDigits(c.scarcity_deadline ?? '');
  const stock = latinDigits(c.stock_units ?? '');
  const w = overlay.layout.box.w;
  const second = useEnter(14, {damping: 13, stiffness: 120});
  const third = useEnter(26, {damping: 13, stiffness: 120});
  const pulse = usePulse(44);

  return (
    <CardShell overlay={overlay}>
      <div
        style={{
          ...ARABIC_TEXT_STYLE,
          width: w,
          boxSizing: 'border-box',
          padding: '56px 52px 58px',
          borderRadius: 52,
          background: 'linear-gradient(160deg, rgba(23,42,107,0.95), rgba(18,10,42,0.95))',
          border: `4px solid ${BRAND.turquoise}`,
          boxShadow: `0 30px 80px rgba(0,0,0,0.55), 0 0 ${36 + 26 * pulse}px rgba(47,198,184,${0.16 + 0.18 * pulse})`,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 30,
          textAlign: 'center',
        }}
      >
        {offer ? (
          <div
            style={{
              fontSize: sizeFor(offer, 104, 88, 70),
              fontWeight: 700,
              lineHeight: 1.3,
              color: BRAND.gold,
              textWrap: 'balance',
              textShadow: '0 4px 18px rgba(0,0,0,0.5)',
            }}
          >
            {offer}
          </div>
        ) : null}
        {offer && guarantee ? <StarDivider width={w - 220} color={BRAND.turquoise} /> : null}
        {guarantee ? (
          <div
            style={{
              display: 'flex',
              flexDirection: 'row',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 22,
              opacity: Math.min(1, second * 1.5),
              transform: `translateY(${(1 - second) * 40}px)`,
            }}
          >
            <ShieldCheck size={84} />
            <span style={{fontSize: sizeFor(guarantee, 68, 58, 50), fontWeight: 600, lineHeight: 1.35, color: BRAND.cream, textWrap: 'balance'}}>
              {guarantee}
            </span>
          </div>
        ) : null}
        {stock || deadline ? (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 10,
              alignItems: 'center',
              opacity: Math.min(1, third * 1.5),
              transform: `translateY(${(1 - third) * 40}px)`,
              background: 'rgba(245,197,66,0.14)',
              border: `2px solid ${BRAND.gold}`,
              borderRadius: 30,
              padding: '14px 36px 18px',
              fontSize: 52,
              fontWeight: 600,
              color: BRAND.gold,
            }}
          >
            {stock ? <span>{`متبقي ${stock} قطعة فقط`}</span> : null}
            {deadline ? <span>{`ينتهي العرض ${deadline}`}</span> : null}
          </div>
        ) : null}
      </div>
    </CardShell>
  );
};
