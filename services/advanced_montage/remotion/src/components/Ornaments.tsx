import React from 'react';
import {BRAND} from '../lib/brand';

// نجمة ثمانية (مربعين متراكبين مدوّرين 45°) — نقش مرسوم بالكود
export const EightStar: React.FC<{size: number; color?: string; opacity?: number; rotate?: number}> = ({
  size,
  color = BRAND.gold,
  opacity = 1,
  rotate = 0,
}) => (
  <svg width={size} height={size} viewBox="-50 -50 100 100" style={{opacity, transform: `rotate(${rotate}deg)`, flex: 'none'}}>
    <rect x="-30" y="-30" width="60" height="60" fill="none" stroke={color} strokeWidth="3.5" strokeLinejoin="round" />
    <rect x="-30" y="-30" width="60" height="60" fill="none" stroke={color} strokeWidth="3.5" strokeLinejoin="round" transform="rotate(45)" />
    <circle r="7" fill={color} />
  </svg>
);

// فاصل ذهبي: خط — نجمة — خط
export const StarDivider: React.FC<{width: number; color?: string}> = ({width, color = BRAND.gold}) => (
  <div style={{display: 'flex', alignItems: 'center', gap: 18, width}}>
    <div style={{flex: 1, height: 3, background: `linear-gradient(90deg, transparent, ${color})`, borderRadius: 2}} />
    <EightStar size={46} color={color} />
    <div style={{flex: 1, height: 3, background: `linear-gradient(270deg, transparent, ${color})`, borderRadius: 2}} />
  </div>
);

export const ShieldCheck: React.FC<{size: number; color?: string}> = ({size, color = BRAND.turquoise}) => (
  <svg width={size} height={size} viewBox="0 0 64 64" style={{flex: 'none'}}>
    <path d="M32 5 L55 13 V31 C55 45 45 55 32 60 C19 55 9 45 9 31 V13 Z" fill="none" stroke={color} strokeWidth="4.5" strokeLinejoin="round" />
    <path d="M21 32 L29 40 L44 23" fill="none" stroke={color} strokeWidth="5.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export const Chevron: React.FC<{size: number; color?: string; opacity?: number}> = ({size, color = BRAND.gold, opacity = 1}) => (
  <svg width={size} height={size * 0.6} viewBox="0 0 60 36" style={{opacity, flex: 'none'}}>
    <path d="M6 6 L30 30 L54 6" fill="none" stroke={color} strokeWidth="8" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

// بلاط نجوم خفيف للخلفية
export const StarPattern: React.FC<{opacity?: number}> = ({opacity = 0.09}) => (
  <svg width="100%" height="100%" style={{position: 'absolute', inset: 0, opacity}}>
    <defs>
      <pattern id="starTile" width="150" height="150" patternUnits="userSpaceOnUse">
        <g transform="translate(75 75)">
          <rect x="-26" y="-26" width="52" height="52" fill="none" stroke={BRAND.gold} strokeWidth="2.5" />
          <rect x="-26" y="-26" width="52" height="52" fill="none" stroke={BRAND.gold} strokeWidth="2.5" transform="rotate(45)" />
        </g>
      </pattern>
    </defs>
    <rect width="100%" height="100%" fill="url(#starTile)" />
  </svg>
);
