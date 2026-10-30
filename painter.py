"""
painter.py - Spike's brushes. Stdlib only.

Painting happens in two passes, the way a person paints from a sketch:
  1. build_scene() lays out what he *means* to paint as flat shapes (sky, mountain, water, barn...).
  2. paint() covers a canvas in brushstrokes that sample colors from that scene.

His skill (0-10) shows up everywhere: wobbly shapes, muddy mixing, color errors and random
stroke directions when he's new; clean edges, strokes that follow the forms and true color when
he's good. The plan's dials (contrast, detail, sharpness, brush, horizon, warmth...) are what his
art-notebook lessons change from one painting to the next.
"""

import math
import random
import re
import struct
import zlib

TIMES = ["dawn", "day", "dusk", "night"]
WEATHERS = ["clear", "cloudy", "rain", "snow", "storm", "fog"]
FOCALS = ["mountain", "bird", "tree", "building", "sun", "water", "tracks", "none"]
BIRDS = ["none", "bolt", "me"]
WHO = ["bolt", "me", "other"]
DOINGS = ["perched", "flying", "synth", "fishing", "tinkering", "reading", "painting", "eating", "singing", "sleeping"]
DOING_WORDS = [   # what a creature's "doing" text means for the painter (Bolt's and Spike's own words)
    ("synth", r"synth|patch|modular|rack"), ("singing", r"song|sing|music|whistl|talk|mimic|call|scold"),
    ("fishing", r"fish"), ("tinkering", r"tinker|build|apart|weld|fix|sift|dig"),
    ("reading", r"read|look(ing)? (something )?up|book|stud"), ("painting", r"paint|draw|sketch"),
    ("eating", r"eat|forag|scaveng|raid|peck|cach|hid"), ("sleeping", r"nap|sleep|rest|roost"),
    ("flying", r"fly|flew|flight")]
MOODS = ["calm", "wild", "gloomy", "bright", "lonely", "proud"]
DIALS = {"contrast": 0.5, "detail": 0.5, "sharpness": 0.5, "brush": 0.5, "horizon": 0.55, "focal_x": 0.5, "warmth": 0.0}

PLACE_SCENES = {
    "fir": ["mountain_far", "ground_forest", "trees_near"],
    "nest": ["mountain_far", "ground_grass", "tree_big", "nest"],
    "junkyard": ["mountain_far", "ground_dirt", "junk"],
    "rail_yard": ["mountain_far", "ground_gravel", "boxcar", "tracks"],
    "river_canyon": ["canyon", "ground_rock", "creek"],
    "garage": ["mountain_far", "ground_pavement", "building"],
    "diner_roof": ["mountain_far", "ground_pavement", "roof"],
    "ambulance_station": ["mountain_far", "ground_pavement", "building"],
    "drift_lot": ["mountain_far", "ground_pavement", "tire_marks"],
    "lake": ["mountain_far", "trees_far", "water"],
    "shed": ["trees_far", "ground_grass", "shed"],
    "mountain_trail": ["mountain_near", "ground_forest", "path", "trees_near"],
    "summit": ["clouds_below", "rock_near"],
    "old_barn": ["mountain_far", "ground_grass", "barn"],
    "machine_shop": ["mountain_far", "ground_pavement", "building"],
}
BUILDING_COLORS = {"garage": (0.55, 0.55, 0.58), "ambulance_station": (0.9, 0.9, 0.88), "machine_shop": (0.45, 0.42, 0.38)}

SKY = {"dawn": ((0.32, 0.42, 0.68), (0.98, 0.72, 0.56)), "day": ((0.28, 0.52, 0.88), (0.74, 0.86, 0.97)),
       "dusk": ((0.18, 0.13, 0.38), (0.98, 0.52, 0.28)), "night": ((0.02, 0.03, 0.09), (0.09, 0.11, 0.24))}
GROUND = {"grass": ((0.36, 0.5, 0.22), (0.2, 0.32, 0.12)), "dirt": ((0.5, 0.4, 0.28), (0.36, 0.27, 0.18)),
          "gravel": ((0.5, 0.47, 0.42), (0.34, 0.31, 0.28)), "pavement": ((0.34, 0.34, 0.36), (0.22, 0.22, 0.24)),
          "forest": ((0.22, 0.3, 0.18), (0.13, 0.17, 0.1)), "rock": ((0.42, 0.38, 0.35), (0.26, 0.23, 0.21))}
MOOD_PALETTES = {"calm": ["#7fa7c9", "#a8c3a0", "#e8d8b0"], "wild": ["#e0402a", "#f2b632", "#2a3d8f"],
                 "gloomy": ["#3d4a5c", "#5c5a52", "#2b2f3a"], "bright": ["#ffd23f", "#3bceac", "#ee4266"],
                 "lonely": ["#5b6c8f", "#9aa5b1", "#d9c6a5"], "proud": ["#2b59c3", "#f5f5f5", "#d4a017"]}
MUD = (0.42, 0.36, 0.3)
JAY_BLUE = (0.16, 0.32, 0.72)


def clamp01(x):
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def mix(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def hex_rgb(h):
    h = str(h).strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        return None
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def normalize_plan(raw, place, time_of_day, weather):
    """Turn whatever the model said into a plan the painter can always execute."""
    raw = raw if isinstance(raw, dict) else {}

    def pick(key, options, default):
        v = str(raw.get(key, "")).strip().lower()
        return v if v in options else default

    def num(key, lo=0.0, hi=1.0):
        try:
            return max(lo, min(hi, float(raw.get(key))))
        except (TypeError, ValueError):
            return DIALS[key]

    mood = pick("mood", MOODS, "calm")
    palette = [c for c in (hex_rgb(x) for x in (raw.get("palette") or [])[:5] if isinstance(raw.get("palette"), list)) if c]
    plan = {
        "place": place, "time": pick("time", TIMES, time_of_day), "weather": pick("weather", WEATHERS, weather),
        "focal": pick("focal", FOCALS, "mountain"), "bird": pick("bird", BIRDS, "none"), "mood": mood,
        "palette": ["#%02x%02x%02x" % tuple(int(v * 255) for v in c) for c in palette] or MOOD_PALETTES[mood],
        "title": re.sub(r"\s+", " ", str(raw.get("title") or "Untitled")).strip()[:60] or "Untitled",
        "intent": re.sub(r"\s+", " ", str(raw.get("intent") or "")).strip()[:240],
    }
    for k in DIALS:
        plan[k] = num(k, -1.0, 1.0) if k == "warmth" else num(k)
    plan["horizon"] = max(0.25, min(0.8, plan["horizon"]))
    figures = []
    for f in (raw.get("figures") if isinstance(raw.get("figures"), list) else [])[:3]:
        if isinstance(f, dict):
            who = str(f.get("who", "")).strip().lower()
            who = who if who in WHO else "bolt" if "bolt" in who or "crow" in who else "me" if who in ("spike", "jay", "myself") else "other"
            figures.append({"who": who, "doing": doing_of(f.get("doing"))})
    if not figures and plan["bird"] != "none":
        figures = [{"who": plan["bird"], "doing": "perched"}]
    plan["figures"] = figures
    plan["things"] = [re.sub(r"\s+", " ", str(t)).strip()[:40] for t in
                      (raw.get("things") if isinstance(raw.get("things"), list) else [])[:4] if str(t).strip()]
    if figures and plan["bird"] == "none":
        plan["bird"] = figures[0]["who"] if figures[0]["who"] in BIRDS else "none"
    return plan


def doing_of(text):
    """Any way of saying what someone's doing, as one of DOINGS."""
    t = str(text or "").strip().lower()
    if t in DOINGS:
        return t
    for doing, pattern in DOING_WORDS:
        if re.search(pattern, t):
            return doing
    return "perched"


class Scene:
    """Flat-shape layout of what he means to paint."""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.px = [(0.0, 0.0, 0.0)] * (w * h)
        self.focus = []        # boxes that get a finishing pass with a small brush (figures and what they're doing)

    def get(self, x, y):
        x = 0 if x < 0 else self.w - 1 if x >= self.w else int(x)
        y = 0 if y < 0 else self.h - 1 if y >= self.h else int(y)
        return self.px[y * self.w + x]

    def _span(self, y, xa, xb, color, alpha):
        xa, xb = max(0, int(xa + 0.5)), min(self.w, int(xb + 0.5))
        if xb <= xa or not 0 <= y < self.h:
            return
        row = y * self.w
        if alpha >= 1:
            self.px[row + xa:row + xb] = [color] * (xb - xa)
        else:
            for i in range(row + xa, row + xb):
                self.px[i] = mix(self.px[i], color, alpha)

    def gradient(self, y0, y1, c0, c1):
        for y in range(max(0, int(y0)), min(self.h, int(y1))):
            self._span(y, 0, self.w, mix(c0, c1, (y - y0) / max(1, y1 - y0)), 1)

    def poly(self, pts, color, alpha=1.0, ymax=None):
        ys = [p[1] for p in pts]
        n = len(pts)
        bottom = max(ys) if ymax is None else min(max(ys), ymax)
        for y in range(max(0, int(min(ys))), min(self.h, int(bottom) + 1)):
            yc = y + 0.5
            xs = sorted(x1 + (yc - y1) * (x2 - x1) / (y2 - y1)
                        for (x1, y1), (x2, y2) in ((pts[i], pts[(i + 1) % n]) for i in range(n))
                        if (y1 <= yc < y2) or (y2 <= yc < y1))
            for a, b in zip(xs[0::2], xs[1::2]):
                self._span(y, a, b, color, alpha)

    def rect(self, x0, y0, x1, y1, color, alpha=1.0):
        self.poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], color, alpha)

    def ellipse(self, cx, cy, rx, ry, color, alpha=1.0):
        for y in range(max(0, int(cy - ry)), min(self.h, int(cy + ry) + 1)):
            dy = (y + 0.5 - cy) / max(ry, 0.5)
            if abs(dy) <= 1:
                dx = rx * math.sqrt(1 - dy * dy)
                self._span(y, cx - dx, cx + dx, color, alpha)


def build_scene(plan, skill, rng, w, h):
    s = skill / 10
    sc = Scene(w, h)
    wob = (1 - s) * 0.04 * w
    jit = lambda pts: [(x + rng.uniform(-wob, wob), y + rng.uniform(-wob, wob)) for x, y in pts]
    pal = [hex_rgb(c) for c in plan["palette"]]
    pal += [pal[i % len(pal)] for i in range(5 - len(pal))]
    hy = int(h * plan["horizon"])
    fx = plan["focal_x"] * w
    weather, tod = plan["weather"], plan["time"]

    # sky
    top, bot = SKY[tod]
    if weather in ("cloudy", "rain", "snow"):
        top, bot = mix(top, (0.55, 0.57, 0.6), 0.5), mix(bot, (0.72, 0.73, 0.75), 0.5)
    elif weather == "storm":
        top, bot = mix(top, (0.15, 0.16, 0.2), 0.7), mix(bot, (0.35, 0.36, 0.4), 0.6)
    elif weather == "fog":
        top, bot = mix(top, (0.78, 0.8, 0.82), 0.6), mix(bot, (0.85, 0.86, 0.87), 0.7)
    sc.gradient(0, hy + 2, mix(top, pal[0], 0.2), mix(bot, pal[0], 0.15))

    if weather in ("clear", "cloudy") and tod != "night":
        big = plan["focal"] == "sun"
        sx = fx if big else w * rng.uniform(0.15, 0.85)
        sun = (1.0, 0.95, 0.7) if tod == "day" else (1.0, 0.6, 0.3)
        sc.ellipse(sx, hy * (0.25 if tod == "day" else 0.7), w * (0.08 if big else 0.04), w * (0.08 if big else 0.04), sun)
    if tod == "night" and weather in ("clear", "cloudy"):
        sc.ellipse(w * rng.uniform(0.6, 0.9), hy * 0.25, w * 0.035, w * 0.035, (0.92, 0.92, 0.85))
    if weather in ("cloudy", "rain", "snow", "storm"):
        cc = (0.3, 0.31, 0.35) if weather == "storm" else (0.82, 0.83, 0.86)
        for _ in range(6 if weather == "storm" else 4):
            cx, cy = rng.uniform(0, w), rng.uniform(0.05, 0.45) * hy
            for k in range(4):
                sc.ellipse(cx + k * w * 0.04, cy + rng.uniform(-6, 6), w * 0.07, h * 0.04, cc, 0.85)

    ground_kind = "grass"
    for feat in PLACE_SCENES.get(plan["place"], PLACE_SCENES["fir"]):
        if feat.startswith("ground_"):
            ground_kind = feat[7:]
            g0, g1 = GROUND[ground_kind]
            if weather == "snow":
                g0, g1 = mix(g0, (0.93, 0.94, 0.97), 0.7), mix(g1, (0.85, 0.87, 0.92), 0.6)
            sc.gradient(hy, h, mix(g0, pal[1], 0.2), mix(g1, pal[1], 0.2))
        elif feat in ("mountain_far", "mountain_near"):
            near = feat == "mountain_near"
            focal = plan["focal"] == "mountain"
            px = fx if focal else w * rng.uniform(0.35, 0.65)
            height = h * (0.55 if near else 0.32) * (1.25 if focal else 1.0)
            half = w * (0.6 if near else 0.42)
            peak_y = hy - height
            # sharp peaks for good sharpness+skill; a rounded lump when either is low
            r = (1 - plan["sharpness"] * (0.4 + 0.6 * s)) * w * 0.14
            cap = [(px - r * math.cos(a), peak_y + r * (1 - math.sin(a)) * 0.6) for a in [i * math.pi / 8 for i in range(9)]]
            body = jit([(px - half, hy + 2), (px - half * 0.45, hy - height * 0.45)]) + cap + \
                jit([(px + half * 0.5, hy - height * 0.4), (px + half, hy + 2)])
            col = mix((0.38, 0.4, 0.55) if not near else (0.3, 0.3, 0.33), pal[3], 0.2)
            if tod == "night":
                col = mix(col, (0.05, 0.05, 0.1), 0.6)
            sc.poly(body, col)
            snow_line = peak_y + height * 0.35
            snow = (0.93, 0.94, 0.98) if tod != "night" else (0.5, 0.52, 0.6)
            sc.poly(body, snow, ymax=snow_line)
            for k in range(4):        # snow streaks running down the gullies
                gx = px + (k - 1.5) * half * 0.12
                sc.poly(jit([(gx - half * 0.03, snow_line - 1), (gx + half * 0.03, snow_line - 1),
                             (gx, snow_line + height * rng.uniform(0.08, 0.2))]), snow)
            if not near:      # Shastina, the little side cone
                sc.poly(jit([(px + half * 0.15, hy + 2), (px + half * 0.42, hy - height * 0.5), (px + half * 0.7, hy + 2)]),
                        mix(col, (0, 0, 0), 0.08))
        elif feat == "canyon":
            dark = (0.32, 0.26, 0.22)
            sc.poly(jit([(0, 0), (w * 0.3, 0), (w * 0.38, hy), (w * 0.42, h), (0, h)]), dark)
            sc.poly(jit([(w, 0), (w * 0.72, 0), (w * 0.62, hy), (w * 0.58, h), (w, h)]), mix(dark, (0, 0, 0), 0.15))
        elif feat == "water":
            for y in range(hy, h):
                src = 2 * hy - y
                if src < 0:
                    src = 0
                row, srow = y * w, src * w
                depth = (y - hy) / max(1, h - hy)
                for x in range(w):
                    sc.px[row + x] = mix(sc.px[srow + min(w - 1, max(0, x + int(math.sin(y * 0.7) * 2)))],
                                         mix((0.12, 0.25, 0.4), pal[2], 0.15), 0.35 + 0.35 * depth)
        elif feat == "creek":
            pts = [(w * (0.45 + 0.08 * math.sin(t * 3)) + (t * 0.25 - 0.1) * w, hy + t * (h - hy)) for t in [i / 8 for i in range(9)]]
            sc.poly(jit(pts + [(x + w * (0.08 + 0.12 * i / 8), y) for i, (x, y) in reversed(list(enumerate(pts)))]),
                    mix((0.3, 0.5, 0.65), pal[2], 0.15))
        elif feat in ("trees_far", "trees_near"):
            near = feat == "trees_near"
            n = 4 if near else 14
            for i in range(n):
                tx = (rng.uniform(0, 0.25) if i % 2 else rng.uniform(0.75, 1.0)) * w if near else rng.uniform(0, w)
                th = h * (rng.uniform(0.35, 0.6) if near else rng.uniform(0.06, 0.12))
                tw = th * 0.35
                base = h if near else hy + 3
                sc.poly(jit([(tx - tw, base), (tx, base - th), (tx + tw, base)]),
                        mix((0.1, 0.22, 0.12), (0, 0, 0), 0.3 if tod == "night" else 0))
        elif feat == "tree_big":
            tx = w * 0.3 if plan["focal"] != "tree" else fx
            sc.rect(tx - w * 0.02, h * 0.3, tx + w * 0.02, h, (0.3, 0.22, 0.15))
            for k in range(5):
                sc.ellipse(tx + rng.uniform(-1, 1) * w * 0.08, h * rng.uniform(0.15, 0.35), w * 0.1, h * 0.09,
                           mix((0.3, 0.42, 0.18), (0.45, 0.5, 0.2), rng.random()))
        elif feat == "nest":
            tx = w * 0.3 if plan["focal"] != "tree" else fx
            sc.ellipse(tx + w * 0.04, h * 0.32, w * 0.06, h * 0.03, (0.38, 0.28, 0.16))
        elif feat == "junk":
            for _ in range(7):
                jx, jw = rng.uniform(0, w), rng.uniform(0.08, 0.18) * w
                jy = hy + rng.uniform(0.05, 0.5) * (h - hy)
                jh = jw * rng.uniform(0.3, 0.6)
                sc.poly(jit([(jx, jy), (jx + jw, jy), (jx + jw * 0.85, jy - jh), (jx + jw * 0.15, jy - jh)]),
                        mix(rng.choice([(0.55, 0.3, 0.15), (0.45, 0.45, 0.5), (0.3, 0.35, 0.4), (0.6, 0.55, 0.2)]), pal[2], 0.15))
        elif feat == "tracks":
            vx = fx if plan["focal"] == "tracks" else w * 0.5
            for k in range(12):
                t = (k / 12) ** 1.6
                y = hy + t * (h - hy)
                half = 0.02 * w + t * 0.45 * w
                sc.rect(vx - half * 1.2, y, vx + half * 1.2, y + 1 + t * 6, (0.3, 0.22, 0.16))
            for side in (-1, 1):
                sc.poly([(vx + side * 0.01 * w, hy), (vx + side * 0.012 * w, hy), (vx + side * 0.47 * w, h), (vx + side * 0.44 * w, h)],
                        (0.55, 0.55, 0.58))
        elif feat == "boxcar":
            bx = w * 0.12
            sc.rect(bx, hy - h * 0.14, bx + w * 0.3, hy + h * 0.03, mix((0.5, 0.18, 0.12), pal[2], 0.2))
            sc.rect(bx + w * 0.12, hy - h * 0.12, bx + w * 0.17, hy + h * 0.02, (0.35, 0.12, 0.08))
        elif feat == "building":
            focal = plan["focal"] == "building"
            bx = fx - w * 0.2 if focal else w * 0.15
            bw, bh = w * (0.45 if focal else 0.35), h * (0.3 if focal else 0.22)
            col = BUILDING_COLORS.get(plan["place"], (0.6, 0.6, 0.6))
            sc.poly(jit([(bx, hy + 4), (bx + bw, hy + 4), (bx + bw, hy - bh), (bx, hy - bh)]), col)
            sc.rect(bx - 4, hy - bh - 6, bx + bw + 4, hy - bh, mix(col, (0.1, 0.1, 0.1), 0.5))
            if plan["place"] == "ambulance_station":
                sc.rect(bx, hy - bh * 0.55, bx + bw, hy - bh * 0.45, (0.8, 0.1, 0.1))
            door = (0.15, 0.15, 0.17) if tod != "night" else (0.95, 0.85, 0.5)
            sc.rect(bx + bw * 0.35, hy - bh * 0.7, bx + bw * 0.75, hy + 4, door)
        elif feat == "roof":
            sc.poly(jit([(0, h * 0.68), (w, h * 0.62), (w, h), (0, h)]), (0.4, 0.38, 0.38))
            sc.rect(w * 0.6, h * 0.5, w * 0.72, h * 0.65, (0.6, 0.6, 0.62))
            for k in range(4):
                sc.ellipse(w * 0.66 + k * 6, h * (0.45 - k * 0.06), 8 + k * 4, 6 + k * 3, (0.85, 0.85, 0.88), 0.5)
        elif feat == "tire_marks":
            for _ in range(3):
                cx, cy, r = rng.uniform(0.2, 0.8) * w, hy + rng.uniform(0.3, 0.7) * (h - hy), rng.uniform(0.08, 0.15) * w
                for a in range(0, 360, 3):
                    t = math.radians(a)
                    sc.ellipse(cx + r * math.cos(t), cy + r * 0.35 * math.sin(t), 2, 1.5, (0.08, 0.08, 0.09))
        elif feat in ("barn", "shed"):
            barn = feat == "barn"
            focal = plan["focal"] == "building"
            bx = fx - w * 0.15 if focal else w * 0.45
            bw, bh = w * (0.32 if barn else 0.2), h * (0.22 if barn else 0.14)
            col = mix((0.6, 0.16, 0.12) if barn else (0.48, 0.4, 0.32), (0.5, 0.5, 0.5), 0.25 if barn else 0)
            sc.poly(jit([(bx, hy + 6), (bx + bw, hy + 6), (bx + bw, hy - bh), (bx, hy - bh)]), col)
            sc.poly(jit([(bx - 4, hy - bh), (bx + bw / 2, hy - bh - bh * 0.6), (bx + bw + 4, hy - bh)]), (0.3, 0.28, 0.27))
            sc.rect(bx + bw * 0.35, hy - bh * 0.65, bx + bw * 0.65, hy + 6, mix(col, (0, 0, 0), 0.4))
        elif feat == "path":
            pts = [(w * (0.5 + 0.2 * math.sin(t * 9)), hy + t * (h - hy)) for t in [i / 10 for i in range(11)]]
            sc.poly(pts + [(x + 4 + 30 * i / 10, y) for i, (x, y) in reversed(list(enumerate(pts)))], (0.62, 0.52, 0.38))
        elif feat == "clouds_below":
            sc.gradient(hy, h, (0.92, 0.93, 0.96), (0.8, 0.82, 0.88))
            for _ in range(10):
                sc.ellipse(rng.uniform(0, w), hy + rng.uniform(0, 0.3) * (h - hy), w * 0.1, h * 0.03, (0.97, 0.97, 0.99), 0.8)
        elif feat == "rock_near":
            sc.poly(jit([(0, h), (0, h * 0.72), (w * 0.25, h * 0.62), (w * 0.5, h * 0.7), (w * 0.8, h * 0.6), (w, h * 0.68), (w, h)]),
                    (0.3, 0.27, 0.27))
            for _ in range(5):
                sc.ellipse(rng.uniform(0, w), h * rng.uniform(0.72, 0.95), w * 0.05, h * 0.015, (0.92, 0.93, 0.97))

    draw_things(sc, plan, rng, w, h, hy)
    figures = plan.get("figures") or []
    spots = {1: [0.5], 2: [0.33, 0.68], 3: [0.22, 0.5, 0.78]}.get(len(figures), [])
    for i, f in enumerate(figures):
        first = i == 0 and plan["focal"] == "bird"
        bx = (fx if len(figures) == 1 and plan["focal"] == "bird" else spots[i] * w)
        size = w * (0.12 if first or len(figures) == 1 else 0.085 if len(figures) == 2 else 0.07)
        by = hy + (h - hy) * 0.45 if f["doing"] != "flying" else hy * rng.uniform(0.35, 0.6)
        draw_figure(sc, f, bx, by, size, rng, pal, tod)
        sc.focus.append((bx - size * 1.7, by - size * 1.8, bx + size * (3.4 if f["doing"] in ("synth", "fishing", "tinkering", "painting") else 2.2),
                         by + size * 1.0))
    return sc


def draw_figure(sc, f, bx, by, size, rng, pal, tod):
    """One bird, big enough to read, with what it's doing around it."""
    crow = f["who"] == "bolt"
    body = (0.05, 0.05, 0.07) if crow else JAY_BLUE if f["who"] == "me" else (0.45, 0.42, 0.38)
    head = (0.05, 0.05, 0.07) if crow else (0.06, 0.07, 0.12) if f["who"] == "me" else (0.35, 0.32, 0.3)
    beak = (0.15, 0.12, 0.1)
    doing = f["doing"]
    down = doing == "eating"                     # head down, pecking
    tucked = doing == "sleeping"
    if doing == "flying":
        sc.ellipse(bx, by, size, size * 0.4, body)
        for side in (-1, 1):
            sc.poly([(bx - size * 0.3, by), (bx + side * size * 0.2 - size * 0.5, by - size * 1.1), (bx + size * 0.4, by)], body)
        sc.ellipse(bx + size * 0.95, by - size * 0.1, size * 0.3, size * 0.3, head)
        sc.poly([(bx + size * 1.2, by - size * 0.15), (bx + size * 1.6, by - size * 0.05), (bx + size * 1.2, by + size * 0.05)], beak)
        return
    sc.ellipse(bx, by + size * 0.75, size * 0.9, size * 0.12, (0.05, 0.05, 0.06), 0.35)          # shadow
    for lx in (-0.2, 0.2):                                                                       # legs
        sc.rect(bx + size * lx - 1, by + size * 0.4, bx + size * lx + 1, by + size * 0.75, (0.25, 0.22, 0.2))
    sc.ellipse(bx, by, size, size * 0.6, body)
    sc.poly([(bx - size * 0.8, by - size * 0.1), (bx - size * 1.6, by + size * 0.25), (bx - size * 0.7, by + size * 0.35)], body)
    hx, hy_ = (bx + size * 0.9, by + size * 0.15) if down else (bx + size * 0.55, by - size * 0.2) if tucked else (bx + size * 0.8, by - size * 0.5)
    sc.ellipse(hx, hy_, size * 0.4, size * 0.4, head)
    if f["who"] == "me" and not tucked:          # the crest
        sc.poly([(hx - size * 0.25, hy_ - size * 0.25), (hx - size * 0.4, hy_ - size * 0.95), (hx + size * 0.15, hy_ - size * 0.3)], head)
    if not tucked:
        sc.ellipse(hx + size * 0.12, hy_ - size * 0.08, size * 0.07, size * 0.07, (0.95, 0.95, 0.95))   # eye
    open_beak = doing == "singing"
    if not tucked:
        sc.poly([(hx + size * 0.3, hy_ - size * 0.08), (hx + size * 0.8, hy_ + (-size * 0.12 if open_beak else 0.02 * size)),
                 (hx + size * 0.3, hy_ + size * 0.08)], beak)
        if open_beak:
            sc.poly([(hx + size * 0.3, hy_ + size * 0.08), (hx + size * 0.75, hy_ + size * 0.22), (hx + size * 0.3, hy_ + size * 0.16)], beak)
    ink = (0.95, 0.92, 0.75) if tod == "night" else (0.1, 0.1, 0.12)
    if doing in ("singing", "synth"):            # music notes rising
        for k in range(3):
            nx, ny = hx + size * (0.9 + k * 0.45), hy_ - size * (0.6 + k * 0.45)
            sc.ellipse(nx, ny, size * 0.12, size * 0.09, ink)
            sc.rect(nx + size * 0.09, ny - size * 0.45, nx + size * 0.13, ny, ink)
    if doing == "synth":                         # the rack: a dark box, knobs, patch cables
        x0, y0 = bx + size * 1.3, by - size * 0.55
        sc.rect(x0, y0, x0 + size * 1.7, y0 + size * 1.2, (0.12, 0.12, 0.14))
        sc.rect(x0, y0 + size * 1.2, x0 + size * 1.7, y0 + size * 1.3, (0.3, 0.3, 0.32))
        for r in range(2):
            for c in range(4):
                sc.ellipse(x0 + size * (0.25 + c * 0.4), y0 + size * (0.3 + r * 0.45), size * 0.1, size * 0.1, (0.85, 0.85, 0.8))
        for c, col in enumerate([(0.9, 0.2, 0.2), (0.95, 0.75, 0.1), (0.2, 0.6, 0.95)]):
            cx0, cx1 = x0 + size * (0.2 + c * 0.45), x0 + size * (0.6 + c * 0.4)
            for t in range(12):
                tt = t / 11
                sc.ellipse(cx0 + (cx1 - cx0) * tt, y0 + size * (0.75 + 0.45 * math.sin(tt * math.pi)), size * 0.05, size * 0.05, col)
    elif doing == "fishing":                     # line from the beak down to a red bobber
        tx, ty = hx + size * 2.2, by + size * 0.9
        for t in range(16):
            tt = t / 15
            sc.ellipse(hx + size * 0.7 + (tx - hx - size * 0.7) * tt, hy_ + (ty - hy_) * tt * tt, 1.2, 1.2, (0.9, 0.9, 0.92))
        sc.ellipse(tx, ty, size * 0.14, size * 0.14, (0.9, 0.15, 0.12))
    elif doing == "tinkering":                   # parts on the ground and sparks
        for k in range(4):
            px_ = bx + size * (1.0 + k * 0.4)
            sc.rect(px_, by + size * 0.45, px_ + size * 0.3, by + size * 0.65, rng.choice([(0.6, 0.6, 0.65), (0.75, 0.6, 0.25), (0.4, 0.4, 0.45)]))
        for k in range(9):
            a = rng.uniform(-2.6, -0.5)
            r = size * rng.uniform(0.4, 0.9)
            sc.ellipse(bx + size * 1.4 + r * math.cos(a), by + size * 0.3 + r * math.sin(a), 1.6, 1.6, (1.0, 0.85, 0.2))
    elif doing == "reading":                     # an open book in front
        x0, y0 = hx + size * 0.5, by + size * 0.15
        sc.poly([(x0, y0), (x0 + size * 0.7, y0 - size * 0.15), (x0 + size * 0.7, y0 + size * 0.45), (x0, y0 + size * 0.55)], (0.95, 0.93, 0.85))
        sc.poly([(x0 + size * 0.7, y0 - size * 0.15), (x0 + size * 1.4, y0), (x0 + size * 1.4, y0 + size * 0.55), (x0 + size * 0.7, y0 + size * 0.45)], (0.88, 0.86, 0.78))
    elif doing == "painting":                    # an easel with a little painting on it
        x0 = bx + size * 1.4
        for lx in (0.0, 0.9):
            sc.poly([(x0 + size * 0.45, by - size * 1.0), (x0 + size * lx, by + size * 0.75), (x0 + size * lx + size * 0.08, by + size * 0.75)], (0.45, 0.3, 0.16))
        sc.rect(x0 + size * 0.05, by - size * 0.9, x0 + size * 0.85, by - size * 0.1, (0.97, 0.96, 0.92))
        for k in range(3):
            sc.ellipse(x0 + size * (0.25 + k * 0.25), by - size * 0.5, size * 0.12, size * 0.1, pal[k % len(pal)])
    elif doing == "eating":                      # seeds where the beak is
        for k in range(5):
            sc.ellipse(hx + size * rng.uniform(0.4, 1.1), by + size * rng.uniform(0.5, 0.75), size * 0.05, size * 0.04, (0.55, 0.4, 0.2))
    elif tucked:                                  # z's
        for k in range(3):
            zx, zy, zs = hx + size * (0.6 + k * 0.35), hy_ - size * (0.6 + k * 0.4), size * (0.16 + k * 0.05)
            sc.rect(zx, zy, zx + zs, zy + 2, ink)
            sc.poly([(zx + zs, zy + 2), (zx + zs, zy + 3), (zx + 1, zy + zs), (zx, zy + zs - 1)], ink)
            sc.rect(zx, zy + zs - 1, zx + zs, zy + zs + 1, ink)


def draw_things(sc, plan, rng, w, h, hy):
    """Things lying around: shiny ones glint, food is small and brown, the rest is a lump of junk."""
    for i, t in enumerate(plan.get("things") or []):
        x = w * (0.12 + 0.76 * (i + 0.5) / max(1, len(plan["things"]))) + rng.uniform(-8, 8)
        y = hy + (h - hy) * rng.uniform(0.7, 0.9)
        low = t.lower()
        if re.search(r"shin|brass|chrome|silver|gold|ring|coin|dime|penny|glass|bottle cap|foil|key|mirror|bearing|wire|lure", low):
            sc.ellipse(x, y, w * 0.018, w * 0.012, (0.85, 0.72, 0.3))
            for a in range(4):                  # the glint
                ang = a * math.pi / 2
                sc.poly([(x, y), (x + math.cos(ang) * w * 0.035, y + math.sin(ang) * w * 0.035), (x + math.cos(ang + 0.2) * w * 0.01, y + math.sin(ang + 0.2) * w * 0.01)],
                        (1.0, 0.97, 0.75))
        elif re.search(r"nut|acorn|seed|berr|worm|fry|bread|crust|peanut|beetle|food|crumb", low):
            for k in range(3):
                sc.ellipse(x + k * 5, y - (k % 2) * 3, w * 0.01, w * 0.008, (0.5, 0.33, 0.16))
        else:
            sc.poly([(x - w * 0.025, y), (x + w * 0.025, y), (x + w * 0.015, y - w * 0.025), (x - w * 0.02, y - w * 0.02)],
                    rng.choice([(0.5, 0.5, 0.55), (0.55, 0.35, 0.2), (0.35, 0.4, 0.45)]))


def paint(scene, plan, skill, rng):
    """Cover a canvas in strokes sampled from the scene. Returns RGB bytes."""
    w, h = scene.w, scene.h
    s = skill / 10
    tgt = scene.px
    lum = [0.3 * r + 0.59 * g + 0.11 * b for r, g, b in tgt]

    # underpainting: blocky and muddy, it's what shows through where strokes miss
    block = int(4 + (1 - s) * 8)
    canvas = [None] * (w * h)
    for by in range(0, h, block):
        for bx in range(0, w, block):
            c = mix(tgt[min(h - 1, by + block // 2) * w + min(w - 1, bx + block // 2)], MUD, 0.25 + (1 - s) * 0.2)
            for y in range(by, min(h, by + block)):
                row = y * w
                for x in range(bx, min(w, bx + block)):
                    canvas[row + x] = c

    scale = w / 400
    base_len = (3 + plan["brush"] * 12) * scale
    n = int((w * h / 120000) * (1500 + 5000 * plan["detail"]) * (0.6 + 0.4 * s) * (8 * scale / base_len))
    k = 0.7 + plan["contrast"] * 0.8
    warm = plan["warmth"] * 0.07
    err = (1 - s) * 0.08 + (0.04 if plan["mood"] == "wild" else 0.0)
    muddy = (1 - s) * 0.22
    fx, fy = plan["focal_x"] * w, plan["horizon"] * h * 0.8

    for _ in range(n):
        if rng.random() < plan["detail"] * 0.35:
            x, y = rng.gauss(fx, w * 0.12), rng.gauss(fy, h * 0.12)
        else:
            x, y = rng.uniform(0, w), rng.uniform(0, h)
        if not (0 <= x < w and 0 <= y < h):
            continue
        r, g, b = scene.get(x, y)
        r, g, b = mix((r + rng.gauss(0, err), g + rng.gauss(0, err), b + rng.gauss(0, err)), MUD, muddy)
        r, g, b = (clamp01(0.5 + (r - 0.5) * k + warm), clamp01(0.5 + (g - 0.5) * k), clamp01(0.5 + (b - 0.5) * k - warm))
        ix, iy = int(x), int(y)
        gx = lum[iy * w + min(w - 1, ix + 2)] - lum[iy * w + max(0, ix - 2)]
        gy = lum[min(h - 1, iy + 2) * w + ix] - lum[max(0, iy - 2) * w + ix]
        grad = math.hypot(gx, gy)
        if grad > 0.02 and rng.random() < 0.3 + 0.7 * s:
            ang = math.atan2(gy, gx) + math.pi / 2          # follow the edge
        elif rng.random() < s:
            ang = rng.gauss(0, 0.25)                         # calm horizontal strokes
        else:
            ang = rng.uniform(0, math.pi)                    # beginner scribble
        length = base_len * (0.6 + rng.random() * 0.8)
        if grad > 0.08:
            length *= 1 - plan["sharpness"] * 0.6 * (0.5 + 0.5 * s)
        width = max(1.0, length * 0.35)
        alpha = 0.55 + 0.35 * rng.random()
        ca, sa = math.cos(ang), math.sin(ang)
        rad = int(length) + 1
        for yy in range(max(0, iy - rad), min(h, iy + rad + 1)):
            dy = yy - y
            row = yy * w
            for xx in range(max(0, ix - rad), min(w, ix + rad + 1)):
                dx = xx - x
                u = (dx * ca + dy * sa) / length
                v = (-dx * sa + dy * ca) / width
                if u * u + v * v <= 1:
                    o = canvas[row + xx]
                    canvas[row + xx] = (o[0] + (r - o[0]) * alpha, o[1] + (g - o[1]) * alpha, o[2] + (b - o[2]) * alpha)

    # finishing pass: small strokes over the figures, so what they're doing still reads
    fine = max(1.5, 2.6 * scale * (1.25 - 0.5 * s))
    for x0, y0, x1, y1 in scene.focus:
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w - 1, x1), min(h - 1, y1)
        for _ in range(int(max(0, (x1 - x0) * (y1 - y0)) / (fine * fine) * (0.5 + 0.9 * s))):
            x, y = rng.uniform(x0, x1), rng.uniform(y0, y1)
            ix, iy = int(x), int(y)
            r, g, b = scene.get(x, y)
            r, g, b = mix((r + rng.gauss(0, err * 0.6), g + rng.gauss(0, err * 0.6), b + rng.gauss(0, err * 0.6)), MUD, muddy * 0.5)
            r, g, b = (clamp01(0.5 + (r - 0.5) * k + warm), clamp01(0.5 + (g - 0.5) * k), clamp01(0.5 + (b - 0.5) * k - warm))
            rad = int(fine) + 1
            for yy in range(max(0, iy - rad), min(h, iy + rad + 1)):
                for xx in range(max(0, ix - rad), min(w, ix + rad + 1)):
                    if (xx - x) ** 2 + (yy - y) ** 2 <= fine * fine * 0.6:
                        o = canvas[yy * w + xx]
                        canvas[yy * w + xx] = (o[0] + (r - o[0]) * 0.85, o[1] + (g - o[1]) * 0.85, o[2] + (b - o[2]) * 0.85)

    hy = int(plan["horizon"] * h)
    if plan["weather"] == "rain" or plan["weather"] == "storm":
        for _ in range(int(w * h / 900)):
            x0, y0 = rng.uniform(0, w), rng.uniform(0, h)
            for t in range(int(10 * scale) + 2):
                xx, yy = int(x0 - t * 0.3), int(y0 + t)
                if 0 <= xx < w and 0 <= yy < h:
                    canvas[yy * w + xx] = mix(canvas[yy * w + xx], (0.75, 0.78, 0.85), 0.45)
    elif plan["weather"] == "snow":
        for _ in range(int(w * h / 500)):
            xx, yy = int(rng.uniform(0, w)), int(rng.uniform(0, h))
            canvas[yy * w + xx] = (0.97, 0.97, 1.0)
    elif plan["weather"] == "fog":
        canvas = [mix(c, (0.82, 0.83, 0.85), 0.3) for c in canvas]
    if plan["time"] == "night" and plan["weather"] in ("clear", "cloudy"):
        for _ in range(int(w * hy / 700)):
            xx, yy = int(rng.uniform(0, w)), int(rng.uniform(0, hy * 0.8))
            canvas[yy * w + xx] = (0.95, 0.95, 0.9)

    # signature: a little blue dab, bottom right
    sx, sy = int(w * 0.95), int(h * 0.95)
    for yy in range(sy - 2, sy + 2):
        for xx in range(sx - 4, sx + 4):
            if 0 <= xx < w and 0 <= yy < h:
                canvas[yy * w + xx] = JAY_BLUE

    out = bytearray(w * h * 3)
    for i, (r, g, b) in enumerate(canvas):
        out[i * 3] = int(clamp01(r) * 255)
        out[i * 3 + 1] = int(clamp01(g) * 255)
        out[i * 3 + 2] = int(clamp01(b) * 255)
    return bytes(out)


def png_bytes(w, h, rgb):
    raw = b"".join(b"\x00" + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def png_ok(data):
    """Cheap validity check for tests: signature, header, and that the pixels decompress to the right size."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    w, h = struct.unpack(">II", data[16:24])
    pos, idat = 8, b""
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        t = data[pos + 4:pos + 8]
        if t == b"IDAT":
            idat += data[pos + 8:pos + 8 + n]
        pos += 12 + n
    try:
        return len(zlib.decompress(idat)) == h * (w * 3 + 1)
    except zlib.error:
        return False


PLACE_WORDS = {
    "fir": ["fir", "pine", "conifer", "evergreen", "forest"], "nest": ["nest", "tree"],
    "junkyard": ["junk", "scrap", "wreck", "debris", "pile", "cars"],
    "rail_yard": ["rail", "track", "train", "railroad", "railway", "boxcar"],
    "river_canyon": ["canyon", "river", "creek", "stream", "gorge", "ravine"],
    "garage": ["garage", "building", "shop", "warehouse"], "diner_roof": ["roof", "rooftop", "chimney", "vent", "steam"],
    "ambulance_station": ["station", "ambulance", "hospital", "building"],
    "drift_lot": ["parking", "lot", "pavement", "asphalt", "tire", "skid"],
    "lake": ["lake", "water", "pond", "reflection", "shore"], "shed": ["shed", "cabin", "hut", "shack"],
    "mountain_trail": ["trail", "path", "hike", "switchback"],
    "summit": ["summit", "peak", "above the clouds", "mountaintop", "sea of clouds"],
    "old_barn": ["barn", "farm", "rural"], "machine_shop": ["shop", "factory", "workshop", "building"],
}
FOCAL_WORDS = {"mountain": ["mountain", "peak", "volcano"], "bird": ["bird", "crow", "jay", "raven"],
               "tree": ["tree"], "building": ["building", "barn", "house", "shed", "cabin"], "sun": ["sun"],
               "water": ["water", "lake", "river", "reflection"], "tracks": ["track", "rail"]}
TIME_WORDS = {"dawn": ["dawn", "sunrise", "early morning", "morning"],
              "day": ["daytime", "midday", "noon", "afternoon", "daylight", "sunny", " day"],
              "dusk": ["dusk", "sunset", "evening", "twilight", "golden hour"],
              "night": ["night", "moon", "midnight", "starry", "stars"]}
WEATHER_WORDS = {"clear": ["clear", "sunny", "cloudless"], "cloudy": ["cloud", "overcast", "grey sky", "gray sky"],
                 "rain": ["rain", "wet", "drizzle", "shower"], "snow": ["snow", "winter", "snowfall"],
                 "storm": ["storm", "thunder", "turbulent"], "fog": ["fog", "mist", "haze"]}
MOOD_WORDS = {"calm": ["calm", "peaceful", "serene", "tranquil", "quiet", "still"],
              "wild": ["wild", "chaotic", "energetic", "dramatic", "intense", "turbulent", "frantic"],
              "gloomy": ["gloomy", "dark", "somber", "sombre", "ominous", "melancholy", "moody", "eerie", "brooding"],
              "bright": ["bright", "cheerful", "happy", "vibrant", "joyful", "lively", "warm"],
              "lonely": ["lonely", "isolated", "solitary", "empty", "desolate", "melancholy"],
              "proud": ["proud", "majestic", "grand", "triumphant", "bold", "heroic", "regal"]}


def recognition(plan, seen):
    """Did a stranger, told nothing, see what he meant? Returns (score 0-1, {check: hit})."""
    def text(*keys):
        return " " + " ".join(str(seen.get(k, "")) for k in keys).lower() + " "

    def hit(words, t):
        return any(w in t for w in words)

    hits = {
        "place": hit(PLACE_WORDS.get(plan["place"], []), text("subject_guess", "sees")),
        "time": hit(TIME_WORDS[plan["time"]], text("time_guess", "sees")),
        "weather": hit(WEATHER_WORDS[plan["weather"]], text("weather_guess", "sees")),
        "mood": hit(MOOD_WORDS[plan["mood"]], text("mood_guess", "sees")),
    }
    if plan["focal"] != "none":
        hits["focal"] = hit(FOCAL_WORDS[plan["focal"]], text("subject_guess", "sees"))
    return sum(hits.values()) / len(hits), hits


def make_painting(plan, skill, seed, w=400, h=300):
    rng = random.Random(seed)
    scene = build_scene(plan, skill, rng, w, h)
    return png_bytes(w, h, paint(scene, plan, skill, rng))
