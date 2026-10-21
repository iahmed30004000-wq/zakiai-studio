import React from 'react';
import {AbsoluteFill} from 'remotion';
import type {Style} from '../lib/types';

// للتطوير فقط (debugSafeZones=true): بيرسم المنطقة الآمنة السفلية 22٪ وهوامش الجنب بخطوط حمرا
export const SafeZones: React.FC<{style: Style}> = ({style}) => {
  const sz = style.safe_zone;
  return (
    <AbsoluteFill style={{pointerEvents: 'none'}}>
      <div style={{position: 'absolute', left: 0, right: 0, bottom: 0, height: sz.bottom_px, background: 'rgba(255,0,0,0.22)', borderTop: '3px dashed #ff4d4d'}} />
      <div style={{position: 'absolute', top: 0, bottom: 0, left: 0, width: sz.side_px, background: 'rgba(255,0,0,0.14)'}} />
      <div style={{position: 'absolute', top: 0, bottom: 0, right: 0, width: sz.side_px, background: 'rgba(255,0,0,0.14)'}} />
    </AbsoluteFill>
  );
};
