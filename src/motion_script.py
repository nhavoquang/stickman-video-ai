"""Viết và kiểm tra "kịch bản chuyển động" (xem prompts/motion_spec.md)."""
import json
import os
import time
from pathlib import Path

import requests

from script_gen import API_URL, available_models

ROOT = Path(__file__).resolve().parent.parent
SPEC = (ROOT / "prompts" / "motion_spec.md").read_text(encoding="utf-8")
DOS = {"camera", "enter", "move", "exit", "action", "expr", "label", "arrow", "line", "highlight",
       "burst", "flow", "shake", "react"}


def build_prompt(topic, plan, notes=""):
    return f"""{SPEC}

---
TASK
Topic: "{topic}"
Language of title/description/tags/narration/labels: {plan['language']}
Aspect ratio: {plan['aspect']} ({'vertical Shorts: fast pace, strong hook' if plan['vertical'] else 'horizontal video'})
Target length: about {plan['duration']} seconds → exactly {plan['scenes']} scenes,
each narration about {plan['seconds_per_scene']} seconds (≈ {plan['words_per_scene_latin']} words for Latin-script languages).
Extra requests from the user: {notes or 'none'}
Content must be factually correct, specific (numbers, concrete examples), told as a story with a strong hook
and a satisfying payoff. Write narration like natural speech; spell out symbols (%, /, &) as words.
Return only the JSON."""


def generate(topic, plan, model="auto", notes=""):
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise SystemExit("Thiếu GEMINI_API_KEY")
    body = {"contents": [{"parts": [{"text": build_prompt(topic, plan, notes)}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.85}}
    models = ([model] if model and model != "auto" else []) + available_models(key)
    models += ["gemini-flash-latest"]
    errors = []
    for m in dict.fromkeys(models):
        for attempt in range(2):
            try:
                r = requests.post(API_URL.format(model=m), params={"key": key}, json=body, timeout=150)
                if r.status_code == 404:
                    break
                if r.status_code in (429, 500, 503):
                    errors.append(f"{m}: HTTP {r.status_code}")
                    time.sleep(8)
                    continue
                if not r.ok:
                    errors.append(f"{m}: HTTP {r.status_code} {r.text[:200]}")
                    break
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                film = clean(json.loads(text))
                print(f"[motion-script] {m}: {len(film['scenes'])} cảnh, "
                      f"{sum(len(s['events']) for s in film['scenes'])} sự kiện — {film['title']}")
                return film
            except requests.Timeout:
                errors.append(f"{m}: timeout")
                break
            except (requests.RequestException, KeyError, IndexError, ValueError) as e:
                errors.append(f"{m}: {e}")
                time.sleep(4)
    raise SystemExit("Gemini lỗi:\n" + "\n".join(errors))


def _num(v, d, lo=-0.5, hi=1.5):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return d


def clean(film):
    """Sửa các lỗi thường gặp để dựng không bị hỏng."""
    film.setdefault("title", "Video")
    film.setdefault("description", "")
    film.setdefault("tags", [])
    film["title"] = str(film["title"]).strip()[:100]
    film["tags"] = [str(t).strip().lstrip("#") for t in film.get("tags", []) if str(t).strip()][:20]
    film["hashtags"] = ["#" + str(h).strip().lstrip("#").replace(" ", "") for h in film.get("hashtags", [])
                        if str(h).strip().lstrip("#")][:5]
    if not isinstance(film.get("thumbnail"), dict):
        film["thumbnail"] = {}
    film.setdefault("art_style", "cute 2D cartoon, bold clean outlines, soft cel shading, vibrant colors")
    film["cast"] = [c for c in film.get("cast", []) if c.get("id") and c.get("prompt")]
    film["props"] = [p for p in film.get("props", []) if p.get("id") and p.get("prompt")]
    film["stages"] = [s for s in film.get("stages", []) if s.get("id") and s.get("prompt")]
    if not film["stages"]:
        film["stages"] = [{"id": "main", "prompt": "a simple colorful background"}]
    stage_ids = {s["id"] for s in film["stages"]}
    ids = {c["id"] for c in film["cast"]} | {p["id"] for p in film["props"]}
    exprs = {c["id"]: set((c.get("expressions") or {}).keys()) for c in film["cast"]}
    scenes = []
    for sc in film.get("scenes", []):
        nar = str(sc.get("narration", "")).strip()
        if not nar:
            continue
        sc["narration"] = nar
        if sc.get("stage") not in stage_ids:
            sc["stage"] = scenes[-1]["stage"] if scenes else film["stages"][0]["id"]
        evs = []
        nwords = len(nar.split())
        for ev in sc.get("events", []) or []:
            do = ev.get("do")
            if do not in DOS:
                continue
            if do in ("enter", "move", "exit", "action", "expr", "flow") and ev.get("id") not in ids:
                continue
            if do == "expr" and ev.get("expr") not in exprs.get(ev.get("id"), set()):
                continue
            ev["at"] = _num(ev.get("at", 0), 0, 0, max(0, nwords - 0.01))
            for k in ("x", "y"):
                if k in ev:
                    ev[k] = _num(ev[k], 0.5)
            evs.append(ev)
        sc["events"] = evs
        scenes.append(sc)
    if not scenes:
        raise ValueError("Kịch bản không có cảnh nào")
    film["scenes"] = scenes
    return film


def asset_jobs(film):
    """Danh sách ảnh cần tạo: (khoá trong assets, loại, prompt)."""
    jobs = []
    for s in film["stages"]:
        jobs.append((f"stage:{s['id']}", "stage", s["prompt"]))
    for c in film["cast"]:
        jobs.append((c["id"], "actor", c["prompt"]))
        for name, pr in (c.get("expressions") or {}).items():
            jobs.append((f"{c['id']}:{name}", "actor", f"{c['prompt']}. {pr}"))
    for p in film["props"]:
        jobs.append((p["id"], "prop", p["prompt"]))
    return jobs
