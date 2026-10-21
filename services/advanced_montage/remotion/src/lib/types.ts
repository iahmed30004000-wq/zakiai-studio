// عقد الـ props = الـ job اللي بيبنيه services/advanced_montage/adapter/build_job.py (بعد stage_media + audio_mix).
// كل المسارات `src` نسبية لمجلد --public-dir (مثل «media/cut_001.mp4»).

export type CutSource = {
  kind: 'video' | 'image';
  src: string | null;
  animation?: string;
};

export type Cut = {
  id: string;
  index: number;
  start_ms: number;
  end_ms: number;
  duration_ms: number;
  start_frame: number;
  end_frame: number;
  source: CutSource;
};

export type CaptionWord = {text: string; start_ms: number; end_ms: number};

export type CaptionLine = {
  id: string;
  text: string;
  start_ms: number;
  end_ms: number;
  start_frame: number;
  end_frame: number;
  words: CaptionWord[];
};

export type Box = {x: number; y: number; w: number; h: number};

export type Overlay = {
  id: string;
  type: 'product' | 'offer' | 'cta';
  start_ms: number;
  end_ms: number;
  start_frame: number;
  end_frame: number;
  content: Record<string, string>;
  layout: {zone: string; static: boolean; dir: string; backdrop: boolean; box: Box};
};

export type Audio = {
  voice?: {src: string | null; duration_ms: number; rate: number} | null;
  mixed?: {src: string; duration_ms: number; rate: number} | null;
};

export type Style = {
  font: string;
  highlight: string;
  highlight_word?: boolean;
  safe_zone: {bottom: number; side: number; bottom_px: number; side_px: number; rect: Box};
  caption: {anchor: string; bottom_px: number; band_h: number; max_chars: number};
};

export type Job = {
  version: number;
  script_id: string;
  width: number;
  height: number;
  fps: number;
  duration_ms: number;
  total_frames: number;
  cuts: Cut[];
  captions: CaptionLine[];
  overlays: Overlay[];
  audio: Audio;
  product: Record<string, string>;
  style: Style;
  output?: {w: number; h: number; fps: number};
};

// Remotion بيمرّر الـ props كـ Record — نلفّ الـ job بمفتاح واحد؟ لا: الـ props = الـ job نفسه (حقول مباشرة)
export type AdProps = Job;
