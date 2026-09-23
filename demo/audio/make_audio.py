"""Original soundtrack + SFX for the Sarge demo, synthesized from scratch (no samples, no licensing).

120 BPM, 30 fps video -> 1 beat = 15 frames = 0.5 s. Cues are in video frames.
"""
import json
import sys

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, fftconvolve, sosfilt

SR = 44100
FPS = 30
DUR = 26.5
N = int(SR * DUR)
BEAT = 0.5
rng = np.random.default_rng(7)

cues = json.load(open(sys.argv[1]))  # sfx cue frames from the video
OUT = sys.argv[2]

music = np.zeros(N)
sfx = np.zeros(N)
duck = np.ones(N)  # sidechain envelope


def t_(d):
    return np.arange(int(SR * d)) / SR


def place(buf, sig, at_s, gain=1.0):
    i = int(at_s * SR)
    if i >= len(buf):
        return
    j = min(len(buf), i + len(sig))
    buf[i:j] += sig[: j - i] * gain


def lp(x, f, order=2):
    return sosfilt(butter(order, f, "low", fs=SR, output="sos"), x)


def hp(x, f, order=2):
    return sosfilt(butter(order, f, "high", fs=SR, output="sos"), x)


def bp(x, lo, hi, order=2):
    return sosfilt(butter(order, [lo, hi], "band", fs=SR, output="sos"), x)


def env(n, a, d):
    t = np.arange(n) / SR
    e = np.minimum(t / max(a, 1e-4), 1.0) * np.exp(-np.maximum(t - a, 0) / d)
    return e


def note(n):  # midi -> hz
    return 440 * 2 ** ((n - 69) / 12)


# ---------- instruments ----------
def kick(big=False):
    d = 0.9 if big else 0.42
    t = t_(d)
    f = 45 + (170 if big else 120) * np.exp(-t * 28)
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(ph) * np.exp(-t * (3.2 if big else 7.5))
    click = hp(rng.standard_normal(len(t)), 2500) * np.exp(-t * 260) * 0.35
    return np.tanh((body + click) * (2.2 if big else 1.8)) * 0.9


def clap():
    t = t_(0.35)
    n = bp(rng.standard_normal(len(t)), 900, 4200)
    e = np.zeros(len(t))
    for k, off in enumerate([0, 0.011, 0.022]):
        i = int(off * SR)
        e[i:] += np.exp(-(t[: len(t) - i]) * (140 if k < 2 else 18))
    return n * e * 0.55


def hat(open_=False):
    t = t_(0.28 if open_ else 0.06)
    n = hp(rng.standard_normal(len(t)), 7500, 4)
    return n * np.exp(-t * (14 if open_ else 90)) * (0.13 if open_ else 0.10)


def saw(freq, d, detune=(0.0,), cutoff=1800):
    t = t_(d)
    out = np.zeros(len(t))
    for dt in detune:
        f = freq * (1 + dt)
        out += 2 * ((t * f) % 1.0) - 1
    return lp(out / len(detune), cutoff, 2)


def bass(freq, d):
    t = t_(d)
    s = np.sign(np.sin(2 * np.pi * freq * t)) * 0.35 + np.sin(2 * np.pi * freq * t) * 0.8
    s = lp(s, 380, 4)
    return np.tanh(s * 1.6) * env(len(t), 0.004, d * 0.9) * 0.55


def sub_boom(d=2.2):
    t = t_(d)
    f = 38 + 60 * np.exp(-t * 6)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 1.6)


def crash():
    t = t_(2.6)
    n = hp(rng.standard_normal(len(t)), 4000, 2)
    return n * np.exp(-t * 1.9) * 0.3


def riser(d):
    t = t_(d)
    n = rng.standard_normal(len(t))
    out = np.zeros(len(t))
    # sweep a bandpass upward in chunks
    chunks = 40
    L = len(t) // chunks
    for c in range(chunks):
        f = 300 * (40 ** (c / chunks))
        seg = n[c * L:(c + 1) * L]
        out[c * L:(c + 1) * L] = bp(seg, f, min(f * 1.8, SR / 2 - 100))
    tone_f = 110 * (8 ** (t / d))
    tone = np.sin(2 * np.pi * np.cumsum(tone_f) / SR) * 0.25
    return (out * 0.9 + tone) * (t / d) ** 2


def impact():
    t = t_(1.2)
    boom = sub_boom(1.2) * 0.9
    n = lp(rng.standard_normal(len(t)), 1800) * np.exp(-t * 9) * 0.6
    return np.tanh((boom + n) * 1.5)


def whoosh(d=0.45, up=True):
    t = t_(d)
    n = rng.standard_normal(len(t))
    L = len(t) // 24
    out = np.zeros(len(t))
    for c in range(24):
        x = c / 24 if up else 1 - c / 24
        f = 500 * (12 ** x)
        out[c * L:(c + 1) * L] = bp(n[c * L:(c + 1) * L], f, min(f * 2.2, 20000))
    e = np.sin(np.pi * np.clip(t / d, 0, 1)) ** 2
    return out * e * 0.9


def pop(f=900):
    t = t_(0.12)
    fr = f * (1 + 0.8 * np.exp(-t * 60))
    return np.sin(2 * np.pi * np.cumsum(fr) / SR) * np.exp(-t * 38) * 0.5


def key_click():
    t = t_(0.03)
    return hp(rng.standard_normal(len(t)), 3000) * np.exp(-t * 250) * 0.25


def ding(f=1318.5):
    t = t_(1.0)
    s = np.sin(2 * np.pi * f * t) + 0.5 * np.sin(2 * np.pi * f * 2.01 * t) + 0.2 * np.sin(2 * np.pi * f * 3 * t)
    return s * np.exp(-t * 5) * 0.22


def tick_up(n_ticks=10, d=0.9, base=600):
    out = np.zeros(int(SR * d))
    for k in range(n_ticks):
        place(out, pop(base * 2 ** (k / 12 * 1.2)) * 0.5, k * d / n_ticks)
    return out


def glitch():
    t = t_(0.35)
    sq = np.sign(np.sin(2 * np.pi * 180 * t * (1 + 3 * (t % 0.05))))
    n = rng.standard_normal(len(t))
    gate = (np.floor(t * 60) % 2)
    return (sq * 0.3 + n * 0.3) * gate * np.exp(-t * 6) * 0.6


# ---------- arrangement ----------
def s(frame):
    return frame / FPS


DROP = s(150)
END_HIT = s(705)

# Intro: slams on 0,30,60,90 with sub booms; riser into drop; tension pulse
for f in [2, 30, 60]:
    place(music, impact(), s(f), 0.75)
place(music, impact(), s(90), 1.0)
place(sfx, glitch(), s(90), 0.8)
# heartbeat pulse between slams
for b in range(0, 9):
    at = b * BEAT + 0.25
    if at < DROP - 0.6:
        place(music, lp(kick(), 140) * 0.35, at)
place(music, riser(DROP - s(96) - 0.12), s(96), 0.55)

# Drop + groove from 5s to 22.5s
chords = [  # A minor: Am F C G (one bar each = 2s)
    (45, [57, 60, 64]), (41, [57, 60, 65]), (48, [55, 60, 64]), (43, [55, 59, 62]),
]
place(music, kick(big=True), DROP, 1.0)
place(music, crash(), DROP, 0.9)
place(music, sub_boom(), DROP, 0.7)

bar = 4 * BEAT
t0 = DROP
groove_end = END_HIT
beat_i = 0
while True:
    at = t0 + beat_i * BEAT
    if at >= groove_end - 1e-6:
        break
    # kick every beat, except a 2-beat break right before the end card
    in_break = s(675) <= at < s(705)
    if not in_break or (beat_i % 2 == 0):
        if beat_i > 0:
            place(music, kick(), at, 0.95)
        di = int(at * SR)
        dl = int(0.28 * SR)
        e = 1 - 0.75 * np.exp(-np.arange(dl) / SR * 12)
        j = min(N, di + dl)
        duck[di:j] = np.minimum(duck[di:j], e[: j - di])
    if beat_i % 2 == 1:
        place(music, clap(), at, 0.9)
    # 16th hats, offbeat open hat
    for k in range(4):
        vel = [0.7, 0.35, 1.0, 0.45][k]
        if k == 2:
            place(music, hat(open_=True), at + k * BEAT / 4, 0.9)
        else:
            place(music, hat(), at + k * BEAT / 4, vel)
    beat_i += 1

# bass + chord stabs
n_bars = int(np.ceil((groove_end - t0) / bar))
bass_line = []
for bi in range(n_bars):
    root, ch = chords[bi % 4]
    bstart = t0 + bi * bar
    # driving 8th-note bass with octave jump on the "and" of 4
    for k in range(8):
        at = bstart + k * BEAT / 2
        if at >= groove_end:
            break
        n_ = root + (12 if k == 7 else 0)
        bass_line.append((at, n_))
    # offbeat chord stabs
    for k in [1, 3, 5, 6]:
        at = bstart + k * BEAT / 2
        if at >= groove_end:
            break
        stab = sum(saw(note(m + 12), 0.22, detune=(-0.006, 0.0, 0.007), cutoff=2600) for m in ch) / 3
        stab *= env(len(stab), 0.003, 0.09)
        place(music, stab, at, 0.34)
bass_buf = np.zeros(N)
for at, n_ in bass_line:
    place(bass_buf, bass(note(n_), BEAT / 2 * 0.95), at)
# lead hook over the chat scene & ends (simple pentatonic motif, 16ths)
motif = [69, 72, 76, 74, 72, 69, 67, 69]
lead = np.zeros(N)
for rep in range(n_bars):
    bstart = t0 + rep * bar
    if not (s(240) <= bstart < s(630)):
        continue
    if rep % 2 == 1:
        continue
    for k, m in enumerate(motif):
        at = bstart + 2 * BEAT + k * BEAT / 4
        d = BEAT / 4 * 0.9
        x = saw(note(m + 12), d, detune=(-0.004, 0.005), cutoff=3500) * env(int(SR * d), 0.002, 0.06)
        place(lead, x, at, 0.16)

music += bass_buf * duck + lead * duck
# pads under everything after drop (ducked)
pad = np.zeros(N)
for bi in range(n_bars):
    root, ch = chords[bi % 4]
    bstart = t0 + bi * bar
    d = bar
    p = sum(saw(note(m), d, detune=(-0.01, 0.0, 0.011), cutoff=900) for m in ch) / 3
    e = np.minimum(1, np.arange(len(p)) / SR / 0.08) * np.minimum(1, (len(p) - np.arange(len(p))) / SR / 0.1)
    place(pad, p * e, bstart, 0.13)
music += pad * duck

# riser into the end-card hit
place(music, riser(END_HIT - s(678) - 0.05), s(678), 0.4)

# End card hit + ring out
place(music, kick(big=True), END_HIT, 1.0)
place(music, crash(), END_HIT, 1.0)
place(music, sub_boom(3.0), END_HIT, 0.8)
root_chord = sum(saw(note(m), 2.3, detune=(-0.01, 0.0, 0.012), cutoff=1400) for m in [45, 57, 60, 64]) / 4
root_chord *= np.exp(-t_(2.3) * 1.2)
place(music, root_chord, END_HIT, 0.5)

# ---------- SFX from video cues ----------
for f in cues.get("whoosh", []):
    place(sfx, whoosh(0.45), s(f) - 0.3, 0.55)
for f in cues.get("key", []):
    place(sfx, key_click(), s(f), 0.9)
for f in cues.get("pop", []):
    place(sfx, pop(700 + 150 * rng.random()), s(f), 0.7)
for f in cues.get("ding", []):
    place(sfx, ding(), s(f), 0.9)
for f in cues.get("ticks", []):
    place(sfx, tick_up(), s(f), 0.55)
for f in cues.get("thud", []):
    place(sfx, lp(kick(), 400) * 0.6, s(f), 0.8)

# ---------- mix / master ----------
ir_t = t_(1.6)
ir = rng.standard_normal(len(ir_t)) * np.exp(-ir_t * 3.2)
ir = lp(ir, 5000)
ir /= np.sqrt(np.sum(ir ** 2))
wet = fftconvolve(music * 0.5 + sfx * 0.3, ir)[:N] * 0.14
mix = music + sfx + wet
# gentle fade in/out
mix[: int(0.02 * SR)] *= np.linspace(0, 1, int(0.02 * SR))
fo = int(0.8 * SR)
mix[-fo:] *= np.linspace(1, 0, fo) ** 2
mix = lp(hp(mix, 28), 15000)
mix /= np.max(np.abs(mix)) + 1e-9
mix = np.tanh(mix * 1.7) / np.tanh(1.7)  # glue/saturation
mix *= 0.93 / np.max(np.abs(mix))
# stereo: widen hats/lead slightly with a tiny delay on the right
L = mix
R = np.concatenate([mix[:1], mix[:-1]]) * 0.5 + mix * 0.5
st = np.stack([L, R], axis=1)
wavfile.write(OUT, SR, (st * 32767).astype(np.int16))
print("wrote", OUT)
