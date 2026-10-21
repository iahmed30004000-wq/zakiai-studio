import {interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';

// دخول بـ spring (يبدأ بعد delay إطار) وخروج خطي بآخر exitFrames إطار من مدة البطاقة
export const useEnter = (delay = 0, config: {damping?: number; stiffness?: number; mass?: number} = {}): number => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return spring({frame: frame - delay, fps, config: {damping: 15, stiffness: 120, mass: 0.9, ...config}});
};

export const useExit = (durationInFrames: number, exitFrames = 9): number => {
  const frame = useCurrentFrame();
  return interpolate(frame, [durationInFrames - exitFrames, durationInFrames], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
};

// نبضة هادئة مستمرة (0..1..0) لزر أو إطار
export const usePulse = (periodFrames = 36): number => {
  const frame = useCurrentFrame();
  return 0.5 - 0.5 * Math.cos((2 * Math.PI * frame) / periodFrames);
};
