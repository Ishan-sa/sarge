import React from "react";
import { AbsoluteFill, Composition, Sequence } from "remotion";
import { ChatDemo, ColdOpen, EndCard, HowItWorks, Reminders, TitleDrop } from "./scenes";
import { Backdrop, C, Chevrons, Grain, Stripes, display, ui } from "./theme";

export const SCENES = [
  { from: 0, dur: 150, C: ColdOpen },
  { from: 150, dur: 90, C: TitleDrop },
  { from: 240, dur: 210, C: ChatDemo },
  { from: 450, dur: 120, C: Reminders },
  { from: 570, dur: 90, C: HowItWorks },
  { from: 660, dur: 135, C: EndCard },
];

export const SargeDemo: React.FC = () => (
  <AbsoluteFill style={{ backgroundColor: C.bg }}>
    {SCENES.map(({ from, dur, C: Scene }) => (
      <Sequence key={from} from={from} durationInFrames={dur} layout="absolute-fill">
        <Scene />
      </Sequence>
    ))}
    <Grain />
  </AbsoluteFill>
);

export const Banner: React.FC = () => (
  <AbsoluteFill style={{ backgroundColor: C.bg }}>
    <Backdrop glow="rgba(255,90,31,0.30)" glowX={30} glowY={50} />
    <Stripes style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: 26 }} />
    <AbsoluteFill style={{ flexDirection: "row", alignItems: "center", paddingLeft: 140, gap: 60 }}>
      <Chevrons size={190} />
      <div>
        <div
          style={{
            fontFamily: display,
            fontSize: 230,
            lineHeight: 0.9,
            color: C.text,
            letterSpacing: 12,
            textShadow: "0 10px 0 rgba(255,90,31,0.9)",
          }}
        >
          SARGE
        </div>
        <div style={{ fontFamily: ui, fontWeight: 600, fontSize: 46, color: C.text, marginTop: 36 }}>
          The diet coach that <span style={{ color: C.orange }}>yells at you</span> on Telegram.
        </div>
        <div style={{ fontFamily: ui, fontSize: 32, color: C.muted, marginTop: 14 }}>
          Plain-English food logging · Claude Code brain · $0/month, self-hosted
        </div>
      </div>
    </AbsoluteFill>
    <Grain />
  </AbsoluteFill>
);

export const MyComposition = () => (
  <>
    <Composition id="SargeDemo" component={SargeDemo} durationInFrames={795} fps={30} width={1920} height={1080} />
    <Composition id="Banner" component={Banner} durationInFrames={1} fps={30} width={1800} height={600} />
  </>
);
