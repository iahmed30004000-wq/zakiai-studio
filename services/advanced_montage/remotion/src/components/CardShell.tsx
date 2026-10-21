import React from 'react';
import {AbsoluteFill} from 'remotion';
import {useEnter, useExit} from '../lib/anim';
import type {Overlay} from '../lib/types';

// قشرة مشتركة للبطاقات: تحط البطاقة بصندوق الـ layout (داخل المنطقة الآمنة)، دخول spring وخروج بآخر 9 إطارات
export const CardShell: React.FC<{
  overlay: Overlay;
  children: React.ReactNode;
}> = ({overlay, children}) => {
  const duration = overlay.end_frame - overlay.start_frame;
  const enter = useEnter(0, {damping: 14, stiffness: 110});
  const exit = useExit(duration, 9);
  const b = overlay.layout.box;
  return (
    <AbsoluteFill>
      <div
        style={{
          position: 'absolute',
          left: b.x,
          top: b.y,
          width: b.w,
          height: b.h,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          alignItems: 'center',
          opacity: Math.min(1, enter * 1.4) * exit,
          transform: `translateY(${(1 - enter) * 90 - (1 - exit) * 24}px) scale(${0.88 + 0.12 * enter})`,
        }}
      >
        {children}
      </div>
    </AbsoluteFill>
  );
};
