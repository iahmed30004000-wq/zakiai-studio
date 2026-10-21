import React from 'react';
import {AbsoluteFill, Audio, Sequence, staticFile} from 'remotion';
import {ArabicCaptions} from './components/ArabicCaptions';
import {CtaScreen} from './components/CtaScreen';
import {OfferCard} from './components/OfferCard';
import {ProductCard} from './components/ProductCard';
import {ShotLayer} from './components/ShotLayer';
import {SafeZones} from './components/SafeZones';
import {loadFonts} from './lib/fonts';
import type {AdProps, Overlay} from './lib/types';

loadFonts();

const OverlayItem: React.FC<{overlay: Overlay; productName?: string}> = ({overlay, productName}) => {
  switch (overlay.type) {
    case 'product':
      return <ProductCard overlay={overlay} />;
    case 'offer':
      return <OfferCard overlay={overlay} />;
    case 'cta':
      return <CtaScreen overlay={overlay} productName={productName} />;
    default:
      return null;
  }
};

// ترتيب الطبقات: لقطات ← بطاقات (بتتخفى لحالها حسب overlays) ← ترجمة ← صوت مدموج واحد
export const AdVideo: React.FC<AdProps & {debugSafeZones?: boolean}> = (props) => {
  const {cuts, captions, overlays, audio, style, product} = props;
  const audioSrc = audio?.mixed?.src ?? audio?.voice?.src ?? null;
  return (
    <AbsoluteFill style={{background: '#000'}}>
      <ShotLayer cuts={cuts} />
      {(overlays ?? []).map((o) => {
        const frames = o.end_frame - o.start_frame;
        if (frames <= 0) {
          return null;
        }
        return (
          <Sequence key={o.id} from={o.start_frame} durationInFrames={frames} name={o.id}>
            <OverlayItem overlay={o} productName={product?.name} />
          </Sequence>
        );
      })}
      <ArabicCaptions lines={captions ?? []} style={style} />
      {audioSrc ? <Audio src={staticFile(audioSrc)} /> : null}
      {props.debugSafeZones ? <SafeZones style={style} /> : null}
    </AbsoluteFill>
  );
};
