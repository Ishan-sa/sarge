import React from "react";
import { AbsoluteFill, Easing, random, useCurrentFrame } from "remotion";
import { Backdrop, C, Chevrons, Flash, Stripes, display, inOut, ip, mono, outExpo, shake, ui } from "./theme";

/* ---------------- 1. Cold open (150f) ---------------- */
const SLAMS = [
  { t: "YOU SAID", f: 2 },
  { t: "YOU'D TRACK", f: 30 },
  { t: "EVERY MEAL.", f: 60 },
  { t: "YOU DIDN'T.", f: 90, hot: true },
];

export const ColdOpen: React.FC = () => {
  const f = useCurrentFrame();
  const cur = [...SLAMS].reverse().find((s) => f >= s.f);
  const sh = cur ? shake(f, cur.f, cur.hot ? 28 : 14, cur.t) : { x: 0, y: 0 };
  const glitching = cur?.hot && f < 104;
  return (
    <AbsoluteFill style={{ backgroundColor: C.bg }}>
      <Backdrop glow={cur?.hot ? "rgba(255,40,20,0.28)" : "rgba(255,255,255,0.05)"} />
      {cur && f < 142 && (
        <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", translate: `${sh.x}px ${sh.y}px` }}>
          {glitching &&
            [C.orange, "#19E3FF"].map((col, i) => (
              <div
                key={col}
                style={{
                  position: "absolute",
                  fontFamily: display,
                  fontSize: 250,
                  color: col,
                  opacity: 0.7,
                  mixBlendMode: "screen",
                  translate: `${(random(`gx${i}${f}`) - 0.5) * 40}px ${(random(`gy${i}${f}`) - 0.5) * 12}px`,
                  clipPath: `inset(${random(`c${i}${f}`) * 60}% 0 ${random(`d${i}${f}`) * 30}% 0)`,
                }}
              >
                {cur.t}
              </div>
            ))}
          <div
            style={{
              fontFamily: display,
              fontSize: 250,
              letterSpacing: 2,
              color: cur.hot ? C.orange : C.text,
              scale: ip(f, [cur.f, cur.f + 7], [1.7, 1], Easing.out(Easing.back(1.4))),
              opacity: ip(f, [cur.f, cur.f + 3], [0, 1]),
              filter: `blur(${ip(f, [cur.f, cur.f + 5], [18, 0])}px)`,
              textShadow: cur.hot ? "0 0 80px rgba(255,90,31,0.55)" : "none",
            }}
          >
            {cur.t}
          </div>
        </AbsoluteFill>
      )}
      {/* tiny caption */}
      <div
        style={{
          position: "absolute",
          bottom: 90,
          width: "100%",
          textAlign: "center",
          fontFamily: mono,
          fontSize: 26,
          color: C.muted,
          letterSpacing: 6,
          opacity: ip(f, [100, 112, 136, 142], [0, 1, 1, 0]),
        }}
      >
        DAY 3 · 2,740 CAL · "IT WAS A CHEAT MEAL"
      </div>
      {cur && <Flash at={cur.f} strength={cur.hot ? 0.5 : 0.18} color={cur.hot ? C.orange : "#fff"} />}
    </AbsoluteFill>
  );
};

/* ---------------- 2. Title drop (90f) ---------------- */
export const TitleDrop: React.FC = () => {
  const f = useCurrentFrame();
  const sh = shake(f, 0, 30, "title");
  return (
    <AbsoluteFill style={{ backgroundColor: C.bg }}>
      <Backdrop glow="rgba(255,90,31,0.30)" />
      <Stripes
        style={{
          position: "absolute",
          left: -200,
          width: 2400,
          top: 940,
          height: 70,
          rotate: "-4deg",
          translate: `${ip(f, [0, 90], [-300, 0], Easing.linear)}px 0`,
        }}
        opacity={0.9}
      />
      <Stripes
        style={{
          position: "absolute",
          left: -200,
          width: 2400,
          top: 90,
          height: 26,
          rotate: "-4deg",
          translate: `${ip(f, [0, 90], [0, -300], Easing.linear)}px 0`,
        }}
        opacity={0.5}
      />
      <AbsoluteFill
        style={{ justifyContent: "center", alignItems: "center", flexDirection: "column", translate: `${sh.x}px ${sh.y}px` }}
      >
        <div style={{ scale: ip(f, [0, 10], [0.4, 1], Easing.out(Easing.back(2))), marginBottom: 10 }}>
          <Chevrons size={170} draw={ip(f, [0, 14], [0, 1])} />
        </div>
        <div
          style={{
            fontFamily: display,
            fontSize: 360,
            lineHeight: 0.9,
            color: C.text,
            letterSpacing: 18,
            scale: ip(f, [0, 8], [1.35, 1], Easing.out(Easing.cubic)),
            textShadow: "0 12px 0 rgba(255,90,31,0.9), 0 0 120px rgba(255,90,31,0.35)",
          }}
        >
          SARGE
        </div>
        <div
          style={{
            marginTop: 50,
            fontFamily: ui,
            fontWeight: 600,
            fontSize: 50,
            color: C.text,
            opacity: ip(f, [14, 26], [0, 1]),
            translate: `0 ${ip(f, [14, 26], [30, 0])}px`,
          }}
        >
          The diet coach that <span style={{ color: C.orange }}>yells at you</span> on Telegram.
        </div>
      </AbsoluteFill>
      <Flash at={0} strength={1} />
    </AbsoluteFill>
  );
};

/* ---------------- 3. Chat demo (210f) ---------------- */
const USER_MSG = "chicken burrito bowl, 150g chicken, 150g rice, black beans, salsa";
export const TYPE_START = 6;
export const TYPE_END = 50;
export const SEND = 54;
export const REPLY = 84;
export const ITEMS = [
  { e: "🍗", n: "Grilled chicken 150g", k: 248, p: 46 },
  { e: "🍚", n: "Rice 150g", k: 195, p: 4 },
  { e: "🫘", n: "Black beans 80g", k: 106, p: 7 },
  { e: "🍅", n: "Salsa", k: 20, p: 1 },
];
export const ITEM_AT = (i: number) => REPLY + 22 + i * 7;
export const BARS_AT = REPLY + 56;
export const COMMENT_AT = REPLY + 84;
export const NEXT_AT = REPLY + 96;

const Bar: React.FC<{ from: number; value: number; target: number; start: number; color: string }> = ({
  from,
  value,
  target,
  start,
  color,
}) => {
  const f = useCurrentFrame();
  const v = ip(f, [start, start + 26], [from, value], inOut);
  const filled = Math.round((10 * v) / target);
  return (
    <span style={{ letterSpacing: 1 }}>
      {Array.from({ length: 10 }).map((_, i) => (
        <span key={i} style={{ color: i < filled ? color : "#3A3A44" }}>
          {i < filled ? "▰" : "▱"}
        </span>
      ))}
      <span style={{ marginLeft: 14, color: C.text }}>
        {Math.round(v).toLocaleString("en-US")}
      </span>
    </span>
  );
};

const Caption: React.FC<{ from: number; to: number; title: string; sub: string; accent?: string }> = ({
  from,
  to,
  title,
  sub,
  accent = C.orange,
}) => {
  const f = useCurrentFrame();
  if (f < from - 1 || f > to + 1) return null;
  const inO = ip(f, [from, from + 10], [0, 1]);
  const outO = ip(f, [to - 6, to], [1, 0], Easing.in(Easing.quad));
  const words = title.split(" ");
  return (
    <div style={{ position: "absolute", left: 1050, top: 330, width: 780, opacity: outO }}>
      <div style={{ display: "flex", gap: 14, alignItems: "center", marginBottom: 26, opacity: inO }}>
        <div style={{ width: ip(f, [from, from + 14], [0, 70]), height: 8, background: accent }} />
      </div>
      <div style={{ fontFamily: display, fontSize: 132, lineHeight: 0.98, color: C.text }}>
        {words.map((w, i) => (
          <span
            key={i}
            style={{
              display: "inline-block",
              marginRight: 26,
              opacity: ip(f, [from + i * 3, from + i * 3 + 8], [0, 1]),
              translate: `0 ${ip(f, [from + i * 3, from + i * 3 + 10], [60, 0])}px`,
              color: i === words.length - 1 ? accent : C.text,
            }}
          >
            {w}
          </span>
        ))}
      </div>
      <div
        style={{
          marginTop: 30,
          fontFamily: ui,
          fontSize: 38,
          lineHeight: 1.35,
          color: C.muted,
          opacity: ip(f, [from + 8, from + 18], [0, 1]),
        }}
      >
        {sub}
      </div>
    </div>
  );
};

export const ChatDemo: React.FC = () => {
  const f = useCurrentFrame();
  const typed = Math.round(ip(f, [TYPE_START, TYPE_END], [0, USER_MSG.length], Easing.linear));
  const typing = f >= SEND + 4 && f < REPLY;
  const L = (at: number) => ({
    opacity: ip(f, [at, at + 6], [0, 1]),
    translate: `0 ${ip(f, [at, at + 10], [16, 0])}px`,
  });
  // phone scrolls up as the reply grows
  const scroll = ip(f, [REPLY, REPLY + 30], [0, -120], inOut);
  return (
    <AbsoluteFill style={{ backgroundColor: C.bg }}>
      <Backdrop glowX={28} glowY={50} glow="rgba(255,90,31,0.18)" />
      {/* phone */}
      <div
        style={{
          position: "absolute",
          left: 190,
          top: 60,
          width: 700,
          height: 960,
          borderRadius: 64,
          background: "#050506",
          border: "3px solid #2C2C34",
          boxShadow: "0 60px 140px rgba(0,0,0,0.7), 0 0 0 12px #111114, 0 0 120px rgba(255,90,31,0.18)",
          overflow: "hidden",
          scale: ip(f, [0, 18], [0.92, 1]),
          rotate: `${ip(f, [0, 210], [-1.5, 0.5], Easing.linear)}deg`,
          opacity: ip(f, [0, 8], [0, 1]),
        }}
      >
        {/* header */}
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            height: 150,
            paddingTop: 58,
            background: "#141418",
            borderBottom: `1px solid ${C.line}`,
            display: "flex",
            alignItems: "center",
            gap: 20,
            paddingLeft: 36,
            zIndex: 2,
            boxSizing: "border-box",
          }}
        >
          <div
            style={{
              width: 64,
              height: 64,
              borderRadius: 32,
              background: C.orange,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <Chevrons size={38} color="#140800" />
          </div>
          <div>
            <div style={{ fontFamily: ui, fontWeight: 700, fontSize: 30, color: C.text }}>Sarge</div>
            <div style={{ fontFamily: ui, fontSize: 22, color: typing ? C.orange : C.muted }}>
              {typing ? "typing…" : "bot"}
            </div>
          </div>
        </div>
        {/* messages */}
        <div style={{ position: "absolute", top: 170, left: 26, right: 26, translate: `0 ${scroll}px` }}>
          {f >= SEND && (
            <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 22 }}>
              <div
                style={{
                  maxWidth: 520,
                  background: C.orange,
                  color: "#140800",
                  fontFamily: ui,
                  fontWeight: 500,
                  fontSize: 27,
                  lineHeight: 1.35,
                  padding: "18px 24px",
                  borderRadius: "28px 28px 8px 28px",
                  scale: ip(f, [SEND, SEND + 8], [0.6, 1], Easing.out(Easing.back(2))),
                  transformOrigin: "bottom right",
                }}
              >
                {USER_MSG}
              </div>
            </div>
          )}
          {typing && (
            <div
              style={{
                width: 110,
                padding: "22px 26px",
                background: C.panel2,
                borderRadius: "28px 28px 28px 8px",
                display: "flex",
                gap: 12,
              }}
            >
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  style={{
                    width: 14,
                    height: 14,
                    borderRadius: 7,
                    background: C.muted,
                    translate: `0 ${Math.sin((f - i * 4) / 3) * 5}px`,
                  }}
                />
              ))}
            </div>
          )}
          {f >= REPLY && (
            <div
              style={{
                width: 600,
                background: C.panel2,
                border: `1px solid ${C.line}`,
                borderRadius: "28px 28px 28px 8px",
                padding: "26px 30px",
                fontFamily: ui,
                fontSize: 26,
                lineHeight: 1.5,
                color: C.text,
                scale: ip(f, [REPLY, REPLY + 8], [0.8, 1], Easing.out(Easing.back(1.6))),
                transformOrigin: "top left",
                boxSizing: "border-box",
              }}
            >
              <div style={{ ...L(REPLY + 4), fontWeight: 800, fontSize: 29 }}>
                ✅ Logged burrito bowl: 569 cal · 58g protein
              </div>
              <div style={{ ...L(REPLY + 12), color: C.amber, fontWeight: 600 }}>
                Left today: 831 cal · 40g protein
              </div>
              <div style={{ height: 16 }} />
              {ITEMS.map((it, i) => (
                <div key={it.n} style={L(ITEM_AT(i))}>
                  {it.e} {it.n} · {it.k} cal · 💪{it.p}g
                </div>
              ))}
              <div style={{ height: 16 }} />
              <div style={{ ...L(BARS_AT - 4), fontFamily: mono, fontSize: 25 }}>
                🔥 <Bar from={400} value={969} target={1800} start={BARS_AT} color={C.orange} />
                <span style={{ color: C.muted }}> / 1,800 cal</span>
              </div>
              <div style={{ ...L(BARS_AT - 2), fontFamily: mono, fontSize: 25 }}>
                💪 <Bar from={32} value={90} target={130} start={BARS_AT + 4} color={C.green} />
                <span style={{ color: C.muted }}> / 130g protein</span>
              </div>
              <div style={{ height: 16 }} />
              <div style={{ ...L(COMMENT_AT), fontWeight: 600 }}>
                🗣 Now that's a lunch. Don't ruin it with a 4pm cookie.
              </div>
              <div style={{ height: 12 }} />
              <div style={{ ...L(NEXT_AT), color: C.muted }}>⏭ Next: Snack — protein shake + a banana</div>
            </div>
          )}
        </div>
        {/* input bar */}
        <div
          style={{
            position: "absolute",
            bottom: 0,
            left: 0,
            right: 0,
            height: 130,
            background: "rgba(20,20,24,0.98)",
            borderTop: `1px solid ${C.line}`,
            display: "flex",
            alignItems: "center",
            padding: "0 30px 20px",
            boxSizing: "border-box",
            gap: 18,
          }}
        >
          <div
            style={{
              flex: 1,
              minHeight: 68,
              borderRadius: 34,
              background: "#0C0C0F",
              border: `1px solid ${C.line}`,
              padding: "14px 26px",
              fontFamily: ui,
              fontSize: 24,
              lineHeight: 1.3,
              color: f < SEND && typed > 0 ? C.text : C.muted,
              boxSizing: "border-box",
              display: "flex",
              alignItems: "center",
            }}
          >
            {f < SEND && typed > 0 ? (
              <span>
                {USER_MSG.slice(Math.max(0, typed - 34), typed)}
                <span style={{ opacity: Math.floor(f / 8) % 2 ? 1 : 0, color: C.orange }}>|</span>
              </span>
            ) : (
              "Message"
            )}
          </div>
          <div
            style={{
              width: 68,
              height: 68,
              borderRadius: 34,
              background: C.orange,
              scale: f >= SEND - 2 && f < SEND + 4 ? 0.85 : 1,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "#140800",
              fontSize: 34,
              fontWeight: 800,
              fontFamily: ui,
            }}
          >
            ↑
          </div>
        </div>
      </div>

      <Caption from={4} to={REPLY - 2} title="PLAIN ENGLISH IN." sub="No barcode scanning. No food database. Just text what you ate." />
      <Caption from={REPLY} to={COMMENT_AT - 6} title="EXACT MACROS OUT." sub="Claude reads the message. Python does every bit of the math." accent={C.amber} />
      <Caption from={COMMENT_AT - 4} to={214} title="ZERO SYMPATHY." sub="Calories, protein, what's left, and a trainer who doesn't do excuses." />
    </AbsoluteFill>
  );
};

/* ---------------- 4. Reminders (120f) ---------------- */
export const NOTIFS = [
  {
    at: 8,
    time: "08:30",
    text: "Day 12. Yesterday you hit both targets. Don't get comfortable.",
    foot: "🎯 1,800 cal · 130g protein · 3L water · 8k steps",
  },
  { at: 44, time: "13:05", text: "3.5 hours since breakfast. Lunch. Now. Not a granola bar.", foot: "Left today: 1,420 cal · 98g protein" },
  { at: 80, time: "22:00", text: "Protein landed, calories under. That's a day. Tomorrow: drink more water.", foot: "🔥 Streak: 12 days" },
];

export const Reminders: React.FC = () => {
  const f = useCurrentFrame();
  const idx = f < 44 ? 0 : f < 80 ? 1 : 2;
  const clock = NOTIFS[idx].time;
  const changeAt = NOTIFS[idx].at - 8;
  return (
    <AbsoluteFill style={{ backgroundColor: C.bg }}>
      <Backdrop glowX={25} glowY={55} glow="rgba(255,178,26,0.14)" />
      <div style={{ position: "absolute", left: 130, top: 250 }}>
        <div
          style={{
            fontFamily: ui,
            fontWeight: 700,
            fontSize: 34,
            letterSpacing: 8,
            color: C.orange,
            opacity: ip(f, [0, 10], [0, 1]),
          }}
        >
          IT DOESN'T WAIT FOR YOU
        </div>
        <div
          key={clock}
          style={{
            fontFamily: display,
            fontSize: 330,
            lineHeight: 1,
            color: C.text,
            marginTop: 20,
            opacity: ip(f, [changeAt, changeAt + 6], [0, 1]),
            translate: `0 ${ip(f, [changeAt, changeAt + 10], [-80, 0])}px`,
            filter: `blur(${ip(f, [changeAt, changeAt + 6], [12, 0])}px)`,
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {clock}
        </div>
        <div style={{ fontFamily: ui, fontSize: 38, color: C.muted, marginTop: 10, width: 700, lineHeight: 1.35 }}>
          Morning kick-off. Meal nudges 3.5h after you eat. A night review at 10.
        </div>
      </div>
      <div style={{ position: "absolute", right: 110, top: 150, width: 820 }}>
        {NOTIFS.map((n, i) => {
          if (f < n.at) return null;
          const older = NOTIFS.filter((m) => f >= m.at).length - 1 - i;
          return (
            <div
              key={n.time}
              style={{
                marginBottom: 28,
                background: "rgba(28,28,34,0.92)",
                border: `1px solid ${C.line}`,
                borderLeft: `8px solid ${i === 2 ? C.green : C.orange}`,
                borderRadius: 30,
                padding: "28px 34px",
                boxShadow: "0 30px 80px rgba(0,0,0,0.55)",
                translate: `${ip(f, [n.at, n.at + 12], [900, 0])}px 0`,
                rotate: `${ip(f, [n.at, n.at + 12], [6, 0])}deg`,
                opacity: 1 - older * 0.28,
                scale: 1 - older * 0.03,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 12 }}>
                <div
                  style={{
                    width: 46,
                    height: 46,
                    borderRadius: 12,
                    background: C.orange,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  <Chevrons size={28} color="#140800" />
                </div>
                <div style={{ fontFamily: ui, fontWeight: 700, fontSize: 28, color: C.text }}>Sarge</div>
                <div style={{ fontFamily: mono, fontSize: 24, color: C.muted, marginLeft: "auto" }}>{n.time}</div>
              </div>
              <div style={{ fontFamily: ui, fontWeight: 500, fontSize: 32, lineHeight: 1.35, color: C.text }}>{n.text}</div>
              <div style={{ fontFamily: ui, fontSize: 25, color: C.amber, marginTop: 12 }}>{n.foot}</div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

/* ---------------- 5. How it works (90f) ---------------- */
export const ZERO = 48; // "$0/MONTH" lands
const NODES = [
  { icon: "💬", t: "Telegram", s: "you text it" },
  { icon: "🧠", t: "Claude Code", s: "reads it" },
  { icon: "🐍", t: "Python", s: "does the math" },
  { icon: "📊", t: "SQLite + Sheets", s: "keeps the receipts" },
];
export const NODE_AT = (i: number) => 6 + i * 8;

export const HowItWorks: React.FC = () => {
  const f = useCurrentFrame();
  const sh = shake(f, ZERO, 16, "zero");
  return (
    <AbsoluteFill style={{ backgroundColor: C.bg }}>
      <Backdrop glow="rgba(255,90,31,0.12)" glowY={40} />
      <div
        style={{
          position: "absolute",
          top: 110,
          width: "100%",
          textAlign: "center",
          fontFamily: display,
          fontSize: 120,
          color: C.text,
          opacity: ip(f, [0, 8], [0, 1]),
          translate: `0 ${ip(f, [0, 12], [40, 0])}px`,
        }}
      >
        CLAUDE <span style={{ color: C.orange }}>READS.</span> PYTHON <span style={{ color: C.amber }}>COUNTS.</span>
      </div>
      <div style={{ position: "absolute", top: 390, left: 120, right: 120, display: "flex", justifyContent: "space-between" }}>
        {NODES.map((n, i) => (
          <React.Fragment key={n.t}>
            <div
              style={{
                width: 330,
                height: 250,
                borderRadius: 36,
                background: C.panel,
                border: `2px solid ${i === 1 ? C.orange : i === 2 ? C.amber : C.line}`,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                gap: 10,
                boxShadow: i === 1 ? "0 0 70px rgba(255,90,31,0.28)" : "0 20px 60px rgba(0,0,0,0.5)",
                scale: ip(f, [NODE_AT(i), NODE_AT(i) + 10], [0.5, 1], Easing.out(Easing.back(1.8))),
                opacity: ip(f, [NODE_AT(i), NODE_AT(i) + 5], [0, 1]),
              }}
            >
              <div style={{ fontSize: 76 }}>{n.icon}</div>
              <div style={{ fontFamily: ui, fontWeight: 800, fontSize: 36, color: C.text }}>{n.t}</div>
              <div style={{ fontFamily: mono, fontSize: 24, color: C.muted }}>{n.s}</div>
            </div>
            {i < NODES.length - 1 && (
              <div style={{ flex: 1, alignSelf: "center", height: 6, position: "relative", margin: "0 10px" }}>
                <div
                  style={{
                    position: "absolute",
                    inset: 0,
                    background: C.line,
                    borderRadius: 3,
                    transformOrigin: "left",
                    scale: `${ip(f, [NODE_AT(i) + 4, NODE_AT(i) + 12], [0, 1])} 1`,
                  }}
                />
                <div
                  style={{
                    position: "absolute",
                    top: -7,
                    width: 20,
                    height: 20,
                    borderRadius: 10,
                    background: C.orange,
                    boxShadow: `0 0 24px ${C.orange}`,
                    left: `${((f * 3 + i * 33) % 100)}%`,
                    opacity: f > NODE_AT(i) + 12 ? 1 : 0,
                  }}
                />
              </div>
            )}
          </React.Fragment>
        ))}
      </div>
      <div
        style={{
          position: "absolute",
          top: 745,
          width: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          translate: `${sh.x}px ${sh.y}px`,
        }}
      >
        <div
          style={{
            fontFamily: display,
            fontSize: 170,
            lineHeight: 1,
            color: C.green,
            opacity: ip(f, [ZERO, ZERO + 3], [0, 1]),
            scale: ip(f, [ZERO, ZERO + 9], [1.5, 1], Easing.out(Easing.back(1.5))),
            textShadow: "0 0 80px rgba(61,220,132,0.35)",
          }}
        >
          $0/MONTH
        </div>
        <div
          style={{
            marginTop: 22,
            fontFamily: ui,
            fontSize: 38,
            color: C.muted,
            textAlign: "center",
            opacity: ip(f, [ZERO + 6, ZERO + 16], [0, 1]),
            translate: `0 ${ip(f, [ZERO + 6, ZERO + 18], [20, 0])}px`,
          }}
        >
          Runs on your own box with your Claude subscription. No API key.
        </div>
      </div>
      <Flash at={ZERO} strength={0.22} color={C.green} />
    </AbsoluteFill>
  );
};

/* ---------------- 6. End card (135f) ---------------- */
export const EndCard: React.FC = () => {
  const f = useCurrentFrame();
  const HIT = 45; // 1.5s for the protein line, then the logo hits
  const sh = shake(f, HIT, 26, "end");
  return (
    <AbsoluteFill style={{ backgroundColor: C.bg }}>
      <Backdrop glow="rgba(255,90,31,0.28)" />
      {f < HIT && (
        <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
          <div
            style={{
              fontFamily: display,
              fontSize: 170,
              letterSpacing: 2,
              color: C.text,
              display: "flex",
              gap: 44,
              // ease in, slow push while it holds, ease out into the hit
              scale: ip(f, [0, 12, HIT - 8, HIT], [0.86, 1, 1.04, 1.12], outExpo),
              opacity: ip(f, [HIT - 5, HIT], [1, 0], Easing.in(Easing.cubic)),
              filter: `blur(${ip(f, [HIT - 6, HIT], [0, 14], Easing.in(Easing.cubic))}px)`,
            }}
          >
            {["NOW", "EAT", "YOUR", "PROTEIN."].map((w, i) => (
              <span
                key={w}
                style={{
                  display: "inline-block",
                  color: i === 3 ? C.orange : C.text,
                  opacity: ip(f, [i * 5, i * 5 + 8], [0, 1], outExpo),
                  translate: `0 ${ip(f, [i * 5, i * 5 + 12], [70, 0], outExpo)}px`,
                  textShadow: i === 3 ? "0 0 70px rgba(255,90,31,0.5)" : "none",
                }}
              >
                {w}
              </span>
            ))}
          </div>
        </AbsoluteFill>
      )}
      {f >= HIT && (
        <>
          <Stripes
            style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: ip(f, [HIT, HIT + 10], [0, 40]) }}
          />
          <Stripes style={{ position: "absolute", left: 0, right: 0, top: 0, height: ip(f, [HIT, HIT + 10], [0, 40]) }} />
          <AbsoluteFill
            style={{
              justifyContent: "center",
              alignItems: "center",
              flexDirection: "column",
              translate: `${sh.x}px ${sh.y}px`,
              scale: ip(f, [HIT, 135], [1.0, 1.05], Easing.linear),
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 50 }}>
              <div style={{ scale: ip(f, [HIT, HIT + 10], [0.3, 1], Easing.out(Easing.back(2))) }}>
                <Chevrons size={210} draw={ip(f, [HIT, HIT + 14], [0, 1])} />
              </div>
              <div
                style={{
                  fontFamily: display,
                  fontSize: 300,
                  lineHeight: 0.9,
                  color: C.text,
                  letterSpacing: 14,
                  scale: ip(f, [HIT, HIT + 8], [1.4, 1], Easing.out(Easing.cubic)),
                  textShadow: "0 12px 0 rgba(255,90,31,0.9)",
                }}
              >
                SARGE
              </div>
            </div>
            <div
              style={{
                marginTop: 60,
                fontFamily: mono,
                fontWeight: 600,
                fontSize: 44,
                color: C.text,
                background: C.panel2,
                border: `2px solid ${C.line}`,
                padding: "20px 40px",
                borderRadius: 60,
                opacity: ip(f, [HIT + 10, HIT + 20], [0, 1]),
                translate: `0 ${ip(f, [HIT + 10, HIT + 22], [30, 0])}px`,
              }}
            >
              <span style={{ color: C.muted }}>github.com/</span>Ishan-sa/<span style={{ color: C.orange }}>sarge</span>
            </div>
            <div
              style={{
                marginTop: 34,
                fontFamily: ui,
                fontWeight: 600,
                fontSize: 32,
                letterSpacing: 6,
                color: C.muted,
                opacity: ip(f, [HIT + 18, HIT + 28], [0, 1]),
              }}
            >
              OPEN SOURCE · MIT · SELF-HOSTED
            </div>
          </AbsoluteFill>
        </>
      )}
      <Flash at={HIT} strength={0.9} />
      <AbsoluteFill style={{ backgroundColor: "#000", opacity: ip(f, [118, 135], [0, 1], Easing.inOut(Easing.cubic)) }} />
    </AbsoluteFill>
  );
};
