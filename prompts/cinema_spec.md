# Cinema script spec (kiểu dựng "điện ảnh" — giống các Shorts 3D viral)

You direct a short animated FILM, not a motion-graphics slideshow. Every shot is ONE complete AI image of a
3D-animated movie frame: the characters are INSIDE the scene (same lighting, cast shadows, perspective), shot
from a real camera angle. The editor cuts to a new shot every 1.5–3 seconds; each shot only drifts gently.
There are NO overlays: no arrows, labels, circles, icons, flashes, shakes or zoom punches. Words the viewer must
read appear INSIDE the world as signs (a roadside sign, a billboard, a scoreboard, a label on a can).
Small 1–2 word white captions are added automatically.

Measured on "The Instinct That Makes You Crash" (59 s, ~28 shots, 7 hard cuts detected + many soft shot changes,
-14 LUFS, LRA 2.5, no overlay graphics at all).

Return ONLY JSON:

```json
{
  "title": "curiosity title, max 70 chars",
  "description": "YouTube description: hook line with keyword, 2-4 sentences, no hashtags",
  "hashtags": ["#Shorts", "#..."],
  "tags": ["8-15 search phrases"],
  "music": "chill | mystery | upbeat | epic | none",
  "art_style": "stylized 3D animated film still, Pixar-like global illumination, soft realistic shadows, rich detailed environment, saturated natural colors, cinematic depth of field, 35mm lens",
  "characters": [
    {"id": "farmer", "look": "a cartoon character with a big round white egg-shaped head, tiny black dot eyes, thick black eyebrows, thin black stick arms and legs, wearing a red trucker cap and a teal shirt"}
  ],
  "thumbnail": {"text": "2-4 WORD HOOK", "shot": [0, 0]},
  "scenes": [
    {"narration": "Every week a car hits the only tree on this empty road.",
     "shots": [
        {"at": 0, "camera": "push_in", "characters": ["farmer"],
         "prompt": "low angle from the grass: {farmer} kneels planting a seedling beside an empty two-lane country road, wide flat farmland, morning sun"},
        {"at": 6, "camera": "pan_left", "characters": [],
         "prompt": "drone shot high above a perfectly straight road through endless fields, one big lonely oak tree beside it"}
     ]}
  ]
}
```

## Fields
- `characters`: 1–3 recurring characters. `look` is a FIXED visual description (head, face, body, clothes, colors)
  that is pasted verbatim into every shot that names the character, so they look the same in every image.
  Make looks very distinct (different hat + shirt color). Default design: big round white egg-shaped head,
  simple face (dot eyes, bold eyebrows), thin black stick limbs, a costume that shows the role.
- `shots[].prompt`: ONE film frame. Write `{id}` where a character appears (it is replaced by its `look`).
  Always say: camera angle/lens (low angle, over-the-shoulder, drone top-down, through the windshield, extreme
  close-up of the face, wide establishing), what each character is DOING and their facial expression, the
  place, time of day and weather/light. Include in-world text only as short sign text in quotes, max 4 words
  (e.g. a roadside sign reading "DAYS SINCE LAST CRASH: 0").
- `shots[].at`: word index in the narration where the cut happens (first shot at 0, increasing).
- `shots[].camera`: push_in | pull_out | pan_left | pan_right | tilt_up | tilt_down | static. Gentle (~6 %).
- `shots[].characters`: ids that appear (for checking).
- `thumbnail.shot`: [scene index, shot index] of the strongest image.

## Rules
1. A new shot every 1.5–3 s (about every 5–9 words). ~1 shot per sentence minimum. Never hold one image > 3.5 s.
2. Shot variety like a film editor: wide establishing → medium → close-up on reaction → POV/insert. Alternate
   angles; never two similar framings in a row. Cut on the word the image shows ("tree" → we see the tree).
3. ONE world: every shot shares the same place design, palette and light logic. Change the light/weather when
   the story's mood changes (sunny setup → stormy/dark reveal) — mood comes from light, not effects.
4. Show, don't overlay: numbers and key terms live on signs/objects inside the frame. At most one sign per shot.
5. Characters act and emote: running, pointing, fainting, laughing, angry red eyes. The face expression must be
   described in the prompt every time.
6. Story (same as motion_spec rules A–J): paradox hook in sentence 1 (the first shot shows it), a mocker or
   doubter, escalation, a "Wait…" mystery, "You see," + everyday analogy shown as a POV/insert shot, ironic payoff
   that calls back the hook. Shorts end on the last word, no call to action.
7. Narration: plain spoken English with contractions, fast and steady (~3.7 words/s), no greetings.
8. Prompts in English. No real brands, no real celebrities, no gore.
