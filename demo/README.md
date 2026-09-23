# Sarge demo video

The 26-second demo in [`docs/demo.mp4`](../docs/demo.mp4), built with [Remotion](https://www.remotion.dev).
The soundtrack and sound effects are synthesized from scratch in `audio/make_audio.py` (numpy + scipy), so there are no samples and nothing to license.

```bash
npm install
npx remotion studio                      # preview and edit
npm run render                           # -> out/silent.mp4

python3 -m venv .venv && .venv/bin/pip install numpy scipy
.venv/bin/python audio/make_audio.py audio/cues.json out/soundtrack.wav

ffmpeg -i out/silent.mp4 -i out/soundtrack.wav -map 0:v -map 1:a \
  -c:v libx264 -crf 22 -pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart -shortest ../docs/demo.mp4
```

- `src/scenes.tsx`: the six scenes (cold open, title drop, chat, reminders, how it works, end card)
- `src/theme.tsx`: colors, fonts, chevron logo, hazard stripes, grain, shake and flash helpers
- `audio/cues.json`: the frame numbers where the sound effects land. The music is 120 BPM, so one beat is 15 frames at 30 fps.
