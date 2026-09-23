import React from "react";
import { AbsoluteFill, Easing, interpolate, random, useCurrentFrame } from "remotion";
import { loadFont as loadAnton } from "@remotion/google-fonts/Anton";
import { loadFont as loadInter } from "@remotion/google-fonts/Inter";
import { loadFont as loadMono } from "@remotion/google-fonts/JetBrainsMono";

export const display = loadAnton("normal", { weights: ["400"], subsets: ["latin"] }).fontFamily;
export const ui = loadInter("normal", { weights: ["400", "500", "600", "700", "800"], subsets: ["latin"] }).fontFamily;
export const mono = loadMono("normal", { weights: ["400", "600"], subsets: ["latin"] }).fontFamily;

export const C = {
  bg: "#0A0A0C",
  panel: "#141418",
  panel2: "#1C1C22",
  line: "#2A2A33",
  text: "#F4F1EA",
  muted: "#8C8C96",
  orange: "#FF5A1F",
  amber: "#FFB21A",
  green: "#3DDC84",
};

export const outExpo = Easing.bezier(0.16, 1, 0.3, 1);
export const inOut = Easing.bezier(0.65, 0, 0.35, 1);

/** interpolate, always clamped */
export const ip = (
  f: number,
  input: number[],
  output: number[],
  easing: (t: number) => number = outExpo,
) => interpolate(f, input, output, { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing });

/** Decaying camera shake after an impact frame */
export const shake = (f: number, at: number, amp = 18, seed = "s") => {
  const k = f - at;
  if (k < 0 || k > 12) return { x: 0, y: 0 };
  const a = amp * Math.exp(-k / 3.5);
  return { x: (random(`${seed}x${f}`) - 0.5) * 2 * a, y: (random(`${seed}y${f}`) - 0.5) * 2 * a };
};

export const Chevrons: React.FC<{ size: number; color?: string; draw?: number }> = ({
  size,
  color = C.orange,
  draw = 1,
}) => (
  <svg width={size} height={size * 0.9} viewBox="0 0 100 90">
    {[0, 1, 2].map((i) => (
      <path
        key={i}
        d={`M10 ${22 + i * 22} L50 ${4 + i * 22} L90 ${22 + i * 22}`}
        fill="none"
        stroke={color}
        strokeWidth={11}
        strokeLinecap="square"
        strokeLinejoin="miter"
        pathLength={1}
        strokeDasharray={1}
        strokeDashoffset={1 - Math.max(0, Math.min(1, draw * 3 - i))}
      />
    ))}
  </svg>
);

export const Stripes: React.FC<{ style?: React.CSSProperties; opacity?: number }> = ({ style, opacity = 1 }) => (
  <div
    style={{
      background: `repeating-linear-gradient(-45deg, ${C.amber} 0 34px, #111 34px 68px)`,
      opacity,
      ...style,
    }}
  />
);

/** Background: deep black, warm glow, faint grid */
export const Backdrop: React.FC<{ glow?: string; glowX?: number; glowY?: number }> = ({
  glow = "rgba(255,90,31,0.16)",
  glowX = 50,
  glowY = 45,
}) => (
  <AbsoluteFill style={{ backgroundColor: C.bg }}>
    <AbsoluteFill
      style={{
        backgroundImage:
          "linear-gradient(rgba(255,255,255,0.035) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.035) 1px, transparent 1px)",
        backgroundSize: "64px 64px",
        maskImage: "radial-gradient(ellipse at center, black 30%, transparent 75%)",
      }}
    />
    <AbsoluteFill style={{ background: `radial-gradient(circle at ${glowX}% ${glowY}%, ${glow}, transparent 55%)` }} />
  </AbsoluteFill>
);

/** Film grain + vignette on top of everything */
export const Grain: React.FC = () => {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <svg width="100%" height="100%" style={{ position: "absolute", opacity: 0.09, mixBlendMode: "screen" }}>
        <filter id="g">
          <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves={2} seed={f % 12} />
          <feColorMatrix type="saturate" values="0" />
        </filter>
        <rect width="100%" height="100%" filter="url(#g)" />
      </svg>
      <AbsoluteFill style={{ background: "radial-gradient(ellipse at center, transparent 55%, rgba(0,0,0,0.65))" }} />
    </AbsoluteFill>
  );
};

/** White flash that decays */
export const Flash: React.FC<{ at: number; strength?: number; color?: string }> = ({ at, strength = 0.85, color = "#fff" }) => {
  const f = useCurrentFrame();
  const o = f < at ? 0 : ip(f, [at, at + 7], [strength, 0], Easing.out(Easing.quad));
  return <AbsoluteFill style={{ backgroundColor: color, opacity: o, pointerEvents: "none" }} />;
};
