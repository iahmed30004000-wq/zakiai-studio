import React from 'react';
import {CalculateMetadataFunction, Composition} from 'remotion';
import {AdVideo} from './AdVideo';
import {frameOf} from './lib/frames';
import type {AdProps} from './lib/types';

const FPS = 30;
const WIDTH = 1080;
const HEIGHT = 1920;

// props افتراضية صغيرة (للاستوديو فقط). الرندر الحقيقي بيمرّر الـ job الكامل بـ --props.
const defaultProps: AdProps = {
  version: 1,
  script_id: 'demo',
  width: WIDTH,
  height: HEIGHT,
  fps: FPS,
  duration_ms: 3000,
  total_frames: 90,
  cuts: [],
  captions: [],
  overlays: [],
  audio: {},
  product: {},
  style: {
    font: 'IBM Plex Sans Arabic',
    highlight: '#f5c542',
    highlight_word: true,
    safe_zone: {bottom: 0.22, side: 0.06, bottom_px: 422, side_px: 65, rect: {x: 65, y: 0, w: 950, h: 1498}},
    caption: {anchor: 'bottom', bottom_px: 422, band_h: 300, max_chars: 24},
  },
};

// المدة من الـ job: total_frames إن وجد، وإلا من duration_ms. الأبعاد والإطارات ثابتة 1080x1920 بـ 30.
const calculateMetadata: CalculateMetadataFunction<AdProps> = ({props}) => {
  const frames = props.total_frames > 0 ? props.total_frames : frameOf(props.duration_ms, FPS);
  return {durationInFrames: Math.max(1, frames), fps: FPS, width: WIDTH, height: HEIGHT};
};

export const Root: React.FC = () => (
  <Composition
    id="AdVertical"
    component={AdVideo}
    width={WIDTH}
    height={HEIGHT}
    fps={FPS}
    durationInFrames={defaultProps.total_frames}
    defaultProps={defaultProps}
    calculateMetadata={calculateMetadata}
  />
);
