"""Kiểu "film3d": phim hoạt hình 3D dựng bằng code (three.js trong Chromium) — xem prompts/film3d_spec.md.
Kịch bản (Claude/Gemini viết) dùng mốc = chỉ số từ trong lời đọc; ở đây đổi sang giây theo giọng đọc thật,
sinh phụ đề 1–2 chữ, gọi engine3d/render.mjs để dựng hình, rồi ghép giọng + nhạc."""
import json
import os
import subprocess
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "engine3d"
SPEC = (ROOT / "prompts" / "film3d_spec.md").read_text(encoding="utf-8")
FPS = 30
LEAD = 2 / FPS  # hình đổi trước chữ 2 khung
LIGHTS = {"sunny", "golden", "storm", "night", "indoor"}


def build_prompt(topic, plan, notes=""):
    return f"""{SPEC}

---
TASK
Topic: "{topic}"
Language of title/description/tags/narration: {plan['language']} (sign text in the same language)
Aspect ratio: {plan['aspect']} ({'vertical 1080x1920' if plan['vertical'] else 'horizontal 1920x1080'})
Target length: about {plan['duration']} seconds → exactly {plan['scenes']} scenes of about
{plan['words_per_scene_latin']} words each, about {plan['shots_total']} shots in total.
Content brief / extra requests: {notes or 'none'}
Content must be factually correct and specific. Spell out symbols (%, /, &) as words.
Return only the JSON."""


def _num(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _vec(v, d):
    try:
        v = [float(x) for x in v]
        return v if len(v) == 3 else d
    except (TypeError, ValueError):
        return d


def clean(film):
    film.setdefault("title", "Video")
    film.setdefault("description", "")
    film.setdefault("tags", [])
    film.setdefault("music", "chill")
    if film.get("light") not in LIGHTS:
        film["light"] = "sunny"
    world = film.get("world") or {}
    objs = [o for o in world.get("objects", []) or [] if isinstance(o, dict) and o.get("type")]
    if not any(o["type"] == "ground" for o in objs):
        objs.insert(0, {"type": "ground"})
    film["world"] = {"seed": int(_num(world.get("seed"), 7)), "objects": objs}
    scenes = []
    for sc in film.get("scenes", []) or []:
        nar = str(sc.get("narration", "")).strip()
        if not nar:
            continue
        n = len(nar.split())
        shots = []
        for sh in sc.get("shots", []) or []:
            cam = sh.get("cam") or {}
            if "from" not in cam or "look" not in cam:
                continue
            cam["from"] = _vec(cam["from"], [0, 2, 10])
            cam["look"] = _vec(cam["look"], [0, 2, 0])
            for k in ("to", "lookTo"):
                if k in cam:
                    cam[k] = _vec(cam[k], cam["from"] if k == "to" else cam["look"])
            item = {"at": max(0.0, min(n - 0.01, _num(sh.get("at")))), "cam": cam}
            if sh.get("light") in LIGHTS:
                item["light"] = sh["light"]
            shots.append(item)
        if not shots:
            if not scenes:
                continue
            shots = [dict(scenes[-1]["shots"][-1], at=0.0)]
        shots.sort(key=lambda s: s["at"])
        shots[0]["at"] = 0.0
        scenes.append({"narration": nar, "shots": shots, "anim": sc.get("anim") or {}})
    if not scenes:
        raise ValueError("Kịch bản không có cảnh nào")
    film["scenes"] = scenes
    if not isinstance(film.get("thumbnail"), dict):
        film["thumbnail"] = {}
    return film


def generate(topic, plan, model="auto", notes=""):
    import motion_script
    return motion_script.generate(topic, plan, model, notes, prompt=build_prompt(topic, plan, notes), cleaner=clean)


def _word_time(wt, idx, off):
    """Chỉ số từ (có thể lẻ) → giây tuyệt đối."""
    if not wt:
        return off
    i = int(max(0, min(len(wt) - 1, idx)))
    frac = max(0.0, idx - i)
    s, e = wt[i]
    return off + s + (e - s) * min(1.0, frac)


def caption_groups(words):
    out, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= 2 or sum(len(x[2]) for x in cur) > 10 or w[2][-1:] in ",.!?;:…":
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    caps = []
    for i, g in enumerate(out):
        end = out[i + 1][0][0] if i + 1 < len(out) else g[-1][1] + 0.4
        caps.append([round(g[0][0] - 0.03, 3), round(min(end, g[-1][1] + 0.5), 3), " ".join(x[2] for x in g)])
    return caps


def to_render(film, timings, size, subtitles=True):
    """Kịch bản (mốc theo từ) → phim cho engine (mốc theo giây)."""
    shots, anim, words = [], {}, []
    off = 0.0
    for sc, (dur, wt) in zip(film["scenes"], timings):
        for w, (a, b) in zip(sc["narration"].split(), wt):
            words.append((off + a, off + b, w))
        for j, sh in enumerate(sc["shots"]):
            t = _word_time(wt, sh["at"], off) - (LEAD if (j or off) else 0)
            shots.append({"t0": max(0.0, round(t, 3)), "cam": sh["cam"], **({"light": sh["light"]} if "light" in sh else {})})
        for oid, a in (sc.get("anim") or {}).items():
            dst = anim.setdefault(oid, {})
            for k, v in a.items():
                if isinstance(v, list):
                    keys = []
                    for key in v:
                        if isinstance(key, list) and key:
                            keys.append([round(_word_time(wt, _num(key[0]), off), 3)] + key[1:])
                    dst.setdefault(k, []).extend(keys)
                else:
                    dst[k] = v
        off += dur
    for i, s in enumerate(shots):
        s["t1"] = shots[i + 1]["t0"] if i + 1 < len(shots) else round(off, 3)
    shots = [s for s in shots if s["t1"] - s["t0"] > 0.05]
    for a in anim.values():
        for k, v in a.items():
            if isinstance(v, list):
                v.sort(key=lambda x: x[0])
    return {"width": size[0], "height": size[1], "fps": FPS, "light": film.get("light", "sunny"),
            "title": film.get("title", ""), "music": film.get("music", "chill"),
            "world": film["world"], "anim": anim, "shots": shots,
            "captions": caption_groups(words) if subtitles else [], "total": round(off, 3)}


def _node_env():
    env = dict(os.environ)
    try:
        root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
        env["NODE_PATH"] = root + (os.pathsep + env["NODE_PATH"] if env.get("NODE_PATH") else "")
    except OSError:
        pass
    return env


def ensure_engine():
    if not (ENGINE / "node_modules" / "three").exists():
        subprocess.run(["npm", "ci", "--no-audit", "--no-fund"], cwd=ENGINE, check=True)


def render_stills(rfilm, work, out_dir, scale=0.5):
    ensure_engine()
    f = Path(work) / "film3d.json"
    f.write_text(json.dumps(rfilm), encoding="utf-8")
    subprocess.run(["node", str(ENGINE / "render.mjs"), str(f), "x", "--stills", str(out_dir), "--scale", str(scale)],
                   check=True, env=_node_env())
    return sorted(Path(out_dir).glob("shot_*.png"))


def render_video(rfilm, work, voice_wav, out_mp4, qa_dir=None):
    from motion import mix_audio
    ensure_engine()
    work = Path(work)
    f = work / "film3d.json"
    f.write_text(json.dumps(rfilm), encoding="utf-8")
    silent = work / "video_only.mp4"
    total = rfilm["total"]
    # chia khung cho nhiều tiến trình Chromium chạy song song (mỗi lõi CPU một tiến trình), rồi nối lại
    nf = int(round(total * FPS))
    jobs = max(1, min(int(os.environ.get("FILM3D_JOBS", os.cpu_count() or 2)), 6, nf // 60 or 1))
    step = -(-nf // jobs)
    parts, procs = [], []
    for j in range(jobs):
        part = work / f"part_{j}.mp4"
        parts.append(part)
        procs.append(subprocess.Popen(["node", str(ENGINE / "render.mjs"), str(f), str(part), "--from", str(j * step),
                                       "--to", str(min(nf, (j + 1) * step))], env=_node_env()))
    if any(p.wait() != 0 for p in procs):
        raise SystemExit("Dựng 3D lỗi")
    (work / "parts.txt").write_text("".join(f"file '{p.name}'\n" for p in parts))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "parts.txt",
                    "-c", "copy", str(silent.resolve())], check=True, cwd=work)
    sfx = work / "sfx_silent.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                    "-t", f"{total:.2f}", str(sfx)], check=True)
    music = None
    mood = rfilm.get("music") or "chill"
    if mood != "none":
        import music as MUSIC
        music = work / "music.wav"
        seed = zlib.crc32(str(rfilm.get("title", "")).encode()) % 100000
        MUSIC.build(total, music, mood, seed=seed, downbeat_at=0.0)
    mix = mix_audio(voice_wav, sfx, music, work / "mix.wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent), "-i", str(mix), "-map", "0:v", "-map", "1:a",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-shortest", "-movflags", "+faststart",
                    str(out_mp4)], check=True)
    if qa_dir:
        try:
            import qa
            planned = [[int(s["t0"] * FPS) - 1, int(s["t0"] * FPS) + 1] for s in rfilm["shots"]]
            planned += [[int(c[0] * FPS) - 1, int(c[0] * FPS) + 1] for c in rfilm["captions"]]
            planned += [[int(c[1] * FPS) - 1, int(c[1] * FPS) + 1] for c in rfilm["captions"]]
            lines, _ = qa.check(out_mp4, qa_dir, planned)
            print("[qa] " + "\n[qa] ".join(lines))
        except Exception as e:
            print(f"[qa] bỏ qua: {e}")
    return out_mp4


def report(rfilm):
    lens = [round(s["t1"] - s["t0"], 2) for s in rfilm["shots"]]
    return {"total_seconds": rfilm["total"], "shots": len(lens),
            "avg_shot_seconds": round(rfilm["total"] / max(1, len(lens)), 2),
            "too_long_shots": [i + 1 for i, d in enumerate(lens) if d > 3.5], "shot_seconds": lens}
