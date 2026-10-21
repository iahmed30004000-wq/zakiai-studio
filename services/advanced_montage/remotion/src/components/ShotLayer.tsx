import React from 'react';
import {AbsoluteFill, Easing, Img, interpolate, OffthreadVideo, Sequence, staticFile, useCurrentFrame} from 'remotion';
import type {Cut} from '../lib/types';

// صورة ثابتة: حركة Ken Burns ناعمة (تقريب خفيف + انزياح بسيط، تتبدّل الجهة بين لقطة ولقطة)
const KenBurns: React.FC<{src: string; frames: number; index: number}> = ({src, frames, index}) => {
  const frame = useCurrentFrame();
  const t = interpolate(frame, [0, Math.max(1, frames - 1)], [0, 1], {easing: Easing.inOut(Easing.sin)});
  const zoomIn = index % 2 === 0;
  const scale = zoomIn ? 1.04 + 0.10 * t : 1.14 - 0.10 * t;
  const dir = index % 4 < 2 ? 1 : -1;
  const tx = dir * (-18 + 36 * t);
  const ty = (index % 3 === 0 ? -1 : 1) * (-14 + 28 * t);
  return (
    <AbsoluteFill style={{overflow: 'hidden', background: '#000'}}>
      <Img
        src={staticFile(src)}
        style={{width: '100%', height: '100%', objectFit: 'cover', transform: `translate(${tx}px, ${ty}px) scale(${scale})`}}
      />
    </AbsoluteFill>
  );
};

// طبقة اللقطات: كل cut داخل Sequence بإطاراته من الـ job (start_frame/end_frame محسوبة بدون فجوة ولا تداخل)
export const ShotLayer: React.FC<{cuts: Cut[]}> = ({cuts}) => (
  <AbsoluteFill style={{background: '#000'}}>
    {cuts.map((c) => {
      const frames = c.end_frame - c.start_frame;
      if (!c.source.src || frames <= 0) {
        return null;
      }
      return (
        <Sequence key={c.id} from={c.start_frame} durationInFrames={frames} name={`cut ${c.index}`} layout="none">
          <AbsoluteFill>
            {c.source.kind === 'video' ? (
              <OffthreadVideo
                src={staticFile(c.source.src)}
                muted
                style={{width: '100%', height: '100%', objectFit: 'cover'}}
              />
            ) : (
              <KenBurns src={c.source.src} frames={frames} index={c.index} />
            )}
          </AbsoluteFill>
        </Sequence>
      );
    })}
  </AbsoluteFill>
);
