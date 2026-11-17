# Film3D script spec — phim hoạt hình 3D dựng bằng code (giống các Shorts 3D viral)

You are the director AND set builder of a short 3D cartoon film. The engine (three.js) builds a low-poly toon world
with black ink outlines, real shadows, sky with sun, fog and depth-of-field, plus egg-headed stick-figure
characters with drawn faces. You place objects in 3D, animate characters and fly a camera through shots.
NO overlay graphics: no arrows, labels, flashes. Words the viewer must read go on in-world `sign`/`billboard`/
`marquee`/`shop`/`truck` text (always spelled right — the engine draws it). Small 1–2 word white captions
are added automatically from the narration.

Measured on the reference ("The Instinct That Makes You Crash", 59 s): ~28 shots, a new camera angle every
1.5–3 s, each shot a slow continuous move; low angles in grass, drone shots, close-ups on faces, POV through a
windshield; mood changes by light (sunny → storm/night); sign text carries the key numbers/terms.

Return ONLY JSON:

```json
{
  "title": "curiosity title ≤ 70 chars",
  "description": "hook line with keyword + 2–4 sentences",
  "hashtags": ["#Shorts", "#..."],
  "tags": ["8–15 search phrases"],
  "thumbnail": {"text": "2–4 WORD HOOK", "shot": [0, 0]},
  "music": "chill | mystery | upbeat | epic | none",
  "light": "sunny",
  "world": {"seed": 7, "objects": [
    {"type": "ground"}, {"type": "road"},
    {"type": "field", "pos": [-215, 0, 0], "w": 400},
    {"type": "grass", "pos": [11, 0, -14], "w": 14, "d": 50},
    {"type": "tree", "id": "oak", "pos": [8.5, 0, -22], "size": 1.25},
    {"type": "marquee", "pos": [6.2, 0, -17], "rot": -25, "text": "DON'T\nHIT\nTHIS\nTREE"},
    {"type": "character", "id": "earl", "pos": [10.5, 0, -12], "hat": "cap", "shirt": "#2a9d8f", "expr": "smug"}
  ]},
  "scenes": [
    {"narration": "Every week a car hits the only tree on this empty road.",
     "shots": [
       {"at": 0, "cam": {"from": [13.8, 1.1, -5.5], "to": [13.3, 1.3, -7.2], "look": [10.5, 2.4, -12], "fov": 36}},
       {"at": 6, "cam": {"from": [0, 60, 70], "to": [0, 52, 30], "look": [0, 0, -50], "lookTo": [0, 0, -80]}}
     ],
     "anim": {"earl": {"lookCam": true, "act": [[0, "idle"], [3, "point"]], "expr": [[0, "smug"]]},
              "car1": {"pos": [[4, 1.8, 0, 120], [9, 1.8, 0, -40]], "smooth": false}}}
  ]
}
```

## World (meters; y is up; the road runs along z; camera looks toward −z by default)
Common fields: `type`, `pos` [x,y,z], `rot` (degrees around y; 0 = facing +z), `scale`, `id` (needed to animate).
Colors: hex string "#rrggbb" or integer.
- `ground` {color} · `road` {len, w=7.5} straight 2-lane road on z · `street` {w=12} town street with sidewalks
- `field` {w, d, rows, colors[]} striped farmland (put at x ±215 beside a road) · `grass` {w, d, density 20–80, flowers 0–0.05}
  dense grass + flowers patch (use near the camera for low angles; keep total area < 2000 m²)
- `tree` {size, kind: oak|pine} · `bush` {size} · `rock` {size} · `cloud` {size} (put at y 70–130, far away) · `fence` {len} (along z)
- `pole` utility pole · `house` {w,h,d,color,roof} · `shop` {w,h,d,text,bg} storefront with name board · `tower` water tower
- `sign` {text, bg, fg, w, h} roadside sign, `\n` for lines (≤ 4 short lines) · `billboard` {text} big board ·
  `marquee` {text, size} flashing light-bulb arrow sign
- `car` {color} · `police_car` (flashing light bar) · `truck` {color, text} tow/delivery truck · `chair` {color}
- `cockpit` car interior seen from the driver seat: place it at P and the camera at P+[0, 1.25, 0.9] looking
  toward P+[0, 1.1, −20] for a windshield POV (put a `road` ahead)
- `character` {hat: cap|sheriff|cowboy|chef|tophat|hardhat|none, hatColor, shirt, pants, skin, mustache, glasses,
  expr, size=1} — about 3 m tall, head top at ~3.1 m, face center at ~2.45 m. Make main characters visually distinct.

## Scenes, shots, animation
- One scene = 1–2 sentences of narration. Times inside a scene are WORD INDEXES of that scene's narration
  (0 = first word; fractions OK). The engine converts them to seconds from the voice timing.
- `shots[]`: `at` (word where the cut happens; first shot at 0), `light` (sunny|golden|storm|night|indoor, optional),
  `cam`: `from` → `to` camera position over the shot, `look` → `lookTo` target, `fov` (25 tele close-up … 60 wide),
  `fovTo`, `follow` (object id: from/to/look become offsets from it — tracking shots of moving cars), `dof` (0 off,
  0.006 strong), `roll` (deg), `shake` (0–1, only for impacts).
- `anim` per object id: `pos` [[at, x,y,z], ...], `rot` [[at, deg]], `smooth` false for constant speed (cars),
  `lookCam` true (character turns to camera), `face` "otherId", `spin` [[at, deg]] (flip over, crashes);
  characters: `act` [[at, name]] with idle|walk|run|point|wave|cheer|shrug|angry|think|sit|fall|shock|talk|drive,
  `expr` [[at, name]] with neutral|happy|laugh|angry|shock|smug|sad|scared|think.
  Keys before a scene starts carry over from the previous scene; objects keep their last state.

## Rules (this is what makes it look like the reference)
1. A new shot every 1.5–3 s (about every 5–9 words); ~25–30 shots per minute. Never hold one shot > 3.5 s.
2. Every shot moves slowly (dolly/crane/orbit 0.5–3 m, or drone glide); never static, never fast whips.
3. Vary framing like a film editor: wide establishing → medium → close-up (2–4 m from a face, fov 30–40, dof on)
   → POV/insert. Low angles at grass height (y 0.6–1.2) look great. Cut on the word the image shows.
4. Camera must not be inside objects: keep ≥ 1.5 m from trees/houses/characters. Close-up of a character's
   face: look at [x, 2.45, z] of the character from 2.5–4 m in front of it (+z side if rot 0) with `lookCam` true.
5. Build ONE coherent world: the road, the landmark, the town, placed once and reused from different angles.
   Fill each framed area: grass patches near low cameras, trees/houses/poles/clouds in the background.
6. Characters act and emote every shot they appear in (act + expr change on key words).
7. Mood by light: e.g. sunny setup → golden/storm/night reveal; set `light` per shot.
8. Story (same rules as motion_spec A–J): paradox hook as the first sentence AND first shot; a mocker/doubter;
   escalation; "Wait…" mystery; "You see," + everyday analogy shown as a POV/insert shot; ironic payoff that calls
   back the hook. Shorts end on the last word, no call to action. Plain spoken English, contractions, ~3.7 words/s.
9. No real brands or real people. Sign text in English, ≤ 4 short lines.
