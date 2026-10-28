#!/usr/bin/env python3
"""
jay.py - a Steller's jay who lives in the same little town under Mount Shasta as Bolt the crow.

Nobody tells him what to do. Every few minutes he looks around, checks how he feels,
and decides. His brain is a cheap OpenAI model; the world, memory, hoard, skills and
Discord link are plain Python stdlib.

He names himself on his first waking tick.

Run:   python jay.py              needs OPENAI_API_KEY (and JAY_DISCORD_TOKEN for Discord)
Test:  python tests/sim_days.py   days of chaos in seconds, checks nothing breaks
"""

import base64
import copy
import html
import json
import math
import os
import random
import re
import shutil
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import painter

BASE = Path(__file__).resolve().parent

DEFAULT_CONFIG = {
    "model": "gpt-5-nano",
    "reasoning_effort": "minimal",      # set to null if the model rejects it
    "price_in_per_m": 0.05,             # USD per 1M input tokens - check OpenAI's pricing page
    "price_cached_in_per_m": 0.005,
    "price_out_per_m": 0.40,
    "daily_budget_usd": 0.25,           # hard stop: no model calls past this until tomorrow
    "tick_seconds": 300,
    "reflect_every_ticks": 24,          # ~2 hours of waking life
    "discord_channel_id": "",
    "discord_poll_seconds": 20,
    "owner_discord_id": "",             # your Discord user id, for !jay pause / !jay resume
    "bolt_user_id": "",                 # Bolt's bot user id (best); falls back to bolt_name_hint
    "bolt_name_hint": "bolt",
    "bolt_accepts_bots": False,         # flip on once Bolt listens to this bot (enables !give/!leave)
    "max_bolt_messages_per_hour": 4,
    "max_bolt_messages_per_day": 24,
    "min_seconds_between_bolt_messages": 660,   # Bolt hears a creature at most every 10 min, timed from when
                                                # he *reads* it (up to 5 s late); 11 min keeps us clear of that
    "max_gifts_to_bolt_per_day": 3,             # Bolt accepts 3 gifts a day from each creature
    "bolt_streak_limit": 4,                     # Bolt's CREATURE_STREAK: 4 in a row with no human...
    "bolt_streak_rest_seconds": 3660,           # ...then he ignores creatures for an hour (CREATURE_REST + a minute)
    "max_replies_per_hour": 20,
    "post_diary": "special",            # "special" | "all" | "none"
    "daily_painting": True,             # paint one picture at dusk, before sleeping
    "max_paintings_per_day": 6,         # cap on requests (!jay paint); the dusk one always happens
    "paint_width": 400,
    "paint_height": 300,
    "latitude": 41.31,
    "longitude": -122.31,
    # Bolt's own place ids (creature.py PLACES), so his !leave parser matches them exactly.
    # Note his river is "creek": "river canyon lure" would hide "canyon lure" at the creek.
    "bolt_place_names": {
        "nest": "nest", "junkyard": "junkyard", "rail_yard": "rail_yard",
        "river_canyon": "creek", "garage": "garage", "diner_roof": "diner_roof",
        "ambulance_station": "ambulance_station", "drift_lot": "drift_lot", "lake": "lake",
        "shed": "shed", "mountain_trail": "mountain_trail", "summit": "summit",
        "old_barn": "old_barn", "machine_shop": "machine_shop",
    },
}


def load_config(path=None):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    path = Path(path or BASE / "config.json")
    if path.exists():
        user = json.loads(path.read_text(encoding="utf-8"))
        for k, v in user.items():
            if k.startswith("_"):
                continue
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg


# ---------------------------------------------------------------- files

def atomic_write(path, text):
    """Write via tmp + replace so a crash never leaves a half-written file. Keeps a .bak."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    if path.exists():
        try:
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        except OSError:
            pass
    os.replace(tmp, path)


def append_line(path, text):
    with open(path, "a", encoding="utf-8") as f:
        f.write(text + "\n")
        f.flush()
        os.fsync(f.fileno())


def load_json(path, default):
    path = Path(path)
    for p in (path, path.with_name(path.name + ".bak")):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return default


class InstanceLock:
    """One jay at a time. Held for the life of the process; the OS releases it if we die."""

    def __init__(self, path):
        self.path = Path(path)
        self.f = None

    def acquire(self):
        self.f = open(self.path, "a+")
        try:
            if os.name == "nt":
                import msvcrt
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.f.close()
            self.f = None
            return False
        return True


# ---------------------------------------------------------------- text

CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯＀-￯]")
STOP = set("""about above after again against their there these those which while would could should
other being where every still really little thing things maybe just around because before something
again into from that this with what when your have been were they them then than only very some""".split())


def clean(s, n=300):
    s = re.sub(r"\s+", " ", str(s if s is not None else "")).strip()
    return s[:n]


def has_cjk(s):
    return bool(CJK.search(s or ""))


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def parse_json(text):
    text = (text or "").strip()
    for candidate in (text, text[text.find("{"): text.rfind("}") + 1] if "{" in text else ""):
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def match_item(name, options):
    n = clean(name, 80).lower().strip(" .'\"")
    if not n:
        return None
    for o in options:
        if o.lower() == n:
            return o
    for o in options:
        if n in o.lower() or o.lower() in n:
            return o
    return None


def stamp(dt):
    """Bolt's diary timestamp. A post that starts with one is narration to Bolt, not talk."""
    return f"**{dt:%Y-%m-%d %H:%M}**"


def feel(f):
    return f"+{f}" if f > 0 else str(f)


def no_md(text):
    return str(text or "").replace("*", "").strip()


def no_command(text):
    """Model-written text must never start with ! or /: Bolt (and his launcher) treat that as a command."""
    return text.lstrip("!/ \t")


def pick(act, options):
    """The model puts the thing in 'target' or 'item' more or less at random; accept either."""
    return match_item(act.get("target"), options) or match_item(act.get("item"), options)


def overused_words(texts, min_count=5, top=8):
    """Words he keeps leaning on. Names of places and things don't count - those are just facts."""
    counts = {}
    for t in texts:
        for w in set(re.findall(r"[a-z']{5,}", (t or "").lower())):
            if w not in STOP and w not in WORLD_WORDS:
                counts[w] = counts.get(w, 0) + 1
    hot = sorted((c, w) for w, c in counts.items() if c >= min_count)
    return [w for c, w in reversed(hot)][:top]


# ---------------------------------------------------------------- world

def P(name, desc, cost=4, forage=False, raid=False, items=(), sound=None, aliases=(), sights=(), threat="a cat"):
    return dict(name=name, desc=desc, cost=cost, forage=forage, raid=raid, items=list(items),
                sound=sound, aliases=list(aliases), sights=list(sights), threat=threat)


PLACES = {
    "fir": P("the old fir", "your roost: a tall red fir at the edge of town, sap-sticky, with a view over every roof",
             cost=3, forage=True, items=[("pinecone scale", 3), ("bead of hardened sap", 2), ("blue jay feather", 1)],
             sound="chickaree chatter", aliases=["fir"], threat="a chickaree squirrel",
             sights=["a chickaree stealing from the cone pile", "sap glowing amber in the sun",
                     "the whole town laid out below", "the mountain, enormous, right there"]),
    "nest": P("Bolt's nest", "the crow's nest high in a cottonwood. tidy. suspiciously tidy",
              cost=3, items=[("black crow feather", 4), ("twig", 3)], sound="Bolt's caw",
              aliases=["nest"], threat="nobody, but it feels like trespassing",
              sights=["twigs arranged way too neatly", "crow footprints in the dust", "a scrap of paper with scribbles on it"]),
    "junkyard": P("the junkyard", "towers of rusted cars, a sleepy dog, glints everywhere",
                  items=[("bottle cap", 5), ("foil wrapper", 4), ("chrome screw", 3), ("mirror shard", 2),
                         ("old key", 1), ("brass button", 1)],
                  sound="junkyard dog bark", aliases=["junkyard", "junk yard"], threat="the junkyard dog",
                  sights=["the dog asleep on a hood", "a windshield full of sky", "a heap of hubcaps"]),
    "rail_yard": P("the rail yard", "rusty sidings, creosote ties, freight cars that never seem to move",
                   items=[("steel washer", 4), ("flattened penny", 2), ("rail spike", 1), ("signal lamp glass", 1)],
                   sound="train horn", aliases=["rail yard", "railyard", "tracks"], threat="a gang of starlings",
                   sights=["a freight train creaking through", "heat shimmer over the rails", "a penny somebody left on the track"]),
    "river_canyon": P("the river canyon", "a cold creek in a rocky canyon; dippers bob on the stones",
                      forage=True, items=[("agate pebble", 2), ("smooth white quartz", 2), ("tangle of fishing line", 3)],
                      sound="dipper song", aliases=["river canyon", "canyon", "creek", "river"], threat="a mink",
                      sights=["a dipper walking underwater", "trout shadows in a pool", "spray rainbows off the rocks"]),
    "garage": P("the garage", "an open bay door, a radio, a guy under a truck",
                items=[("hex nut", 4), ("chrome valve cap", 3), ("glass fuse", 2), ("spark plug", 1)],
                sound="air wrench", aliases=["garage"], threat="the shop cat",
                sights=["legs sticking out from under a truck", "a coffee can of bolts", "the radio playing old country"]),
    "diner_roof": P("the diner roof", "warm vents, the smell of bacon, a cook who hates birds",
                    raid=True, items=[("soda can tab", 4), ("dime", 1)], sound="diner door bell",
                    aliases=["diner roof", "diner"], threat="the cook",
                    sights=["steam out of the kitchen vent", "a trucker eating pie by the window", "the cook squinting up"]),
    "ambulance_station": P("the ambulance station", "a big bay, a sleepy crew, an ambulance that gets washed a lot",
                           items=[("safety pin", 3), ("rubber band", 4), ("shiny bandage clip", 2)],
                           sound="ambulance siren", aliases=["ambulance station", "ambulance"], threat="a mean crow from out of town",
                           sights=["the crew washing the rig", "lights flashing out of the bay", "somebody's lunch on a bumper"]),
    "drift_lot": P("the drift lot", "a cracked lot with black tire arcs all over it",
                   items=[("lug nut", 3), ("tire valve cap", 4), ("chrome trim strip", 2)],
                   sound="tire squeal", aliases=["drift lot"], threat="a skateboarder",
                   sights=["fresh donut marks", "rubber crumbs everywhere", "a car idling with the bass up"]),
    "lake": P("the lake", "flat water, the mountain upside down in it, picnic tables",
              forage=True, raid=True, items=[("fishing lure", 1), ("red bobber", 2), ("bottle cap", 3)],
              sound="osprey whistle", aliases=["lake"], threat="a gull",
              sights=["an osprey hitting the water", "the mountain reflected perfectly", "a kid feeding ducks"]),
    "shed": P("the shed", "a leaning shed full of cobwebs and coffee cans",
              items=[("baling twine", 3), ("bent nail", 4), ("glass marble", 1)],
              sound="creaky door", aliases=["shed"], threat="a cat",
              sights=["light through the board gaps", "a mouse running the rafters", "cans of mystery screws"]),
    "mountain_trail": P("the mountain trail", "switchbacks through red fir and manzanita",
                        cost=7, forage=True, items=[("obsidian chip", 2), ("perfect pinecone", 3)],
                        sound="pika squeak", aliases=["mountain trail", "trail"], threat="a Cooper's hawk",
                        sights=["hikers huffing up the switchbacks", "a chipmunk with full cheeks", "the summit poking out of cloud"]),
    "summit": P("the summit", "the top of Mount Shasta: wind, ice, rock, the whole world below",
                cost=12, items=[("obsidian chip", 2), ("pumice", 3), ("quartz crystal", 1)],
                sound="red-tailed hawk scream", aliases=["summit", "peak", "top of the mountain"], threat="the wind itself",
                sights=["clouds below you", "a raven riding the wind like it owns it", "the shadow of the mountain"]),
    "old_barn": P("the old barn", "a gray barn with half a roof, owls in the loft",
                  items=[("horseshoe nail", 3), ("baling twine", 2), ("owl pellet", 2)],
                  sound="barn owl screech", aliases=["old barn", "barn"], threat="the barn owl",
                  sights=["dust in the light beams", "an owl staring at you from the loft", "swallow nests on the beam"]),
    "machine_shop": P("the machine shop", "lathes, coolant smell, curls of metal on the floor",
                      items=[("brass shaving", 4), ("ball bearing", 2), ("copper wire", 3)],
                      sound="lathe whine", aliases=["machine shop"], threat="the shop vac",
                      sights=["sparks off a grinder", "a guy measuring something ten times", "brass curls in the light"]),
}
MOUNTAIN = {"mountain_trail", "summit"}

FOODS = {
    "fall": [("black oak acorn", 5), ("sugar pine nut", 4), ("manzanita berry", 3), ("beetle", 3)],
    "winter": [("frozen acorn", 3), ("dried berry", 2), ("spider egg case", 1)],
    "spring": [("caterpillar", 4), ("beetle", 3), ("seed", 3)],
    "summer": [("thimbleberry", 4), ("grasshopper", 4), ("serviceberry", 3), ("beetle", 2)],
}
RAID_FOOD = {
    "diner_roof": [("french fry", 4), ("toast crust", 3), ("pancake corner", 2), ("sugar packet", 2), ("bacon bit", 1)],
    "lake": [("sandwich crust", 3), ("potato chip", 3), ("peanut", 3), ("hot dog bun", 1)],
}
FOOD_ENERGY = {"black oak acorn": 8, "sugar pine nut": 10, "frozen acorn": 6, "peanut": 9, "bacon bit": 12,
               "pancake corner": 10, "french fry": 8, "hot dog bun": 11, "sugar packet": 7}
ALL_FOODS = {n for lst in list(FOODS.values()) + list(RAID_FOOD.values()) for n, _ in lst}
RARES = [("silver ring", 1), ("gold earring", 1), ("old silver dime", 2), ("glass doll eye", 1)]
CACHEABLE_SPROUTS = {"black oak acorn": "an oak seedling", "sugar pine nut": "a tiny sugar pine", "frozen acorn": "an oak seedling"}
SOUND_EFFECTS = {
    "red-tailed hawk scream": "every small bird in earshot vanished",
    "ambulance siren": "a dog somewhere started howling along",
    "train horn": "a guy on the platform actually looked up the tracks",
    "junkyard dog bark": "the junkyard dog woke up and barked back, confused",
    "tire squeal": "somebody turned to see who was drifting",
    "Bolt's caw": "a couple of crows answered from across town",
    "diner door bell": "the waitress looked at the door. nobody there",
}
SKILLS = ["forage", "snatch", "mimic", "recall", "raid", "paint"]
WORLD_WORDS = set(re.findall(r"[a-z']{5,}", " ".join(
    [p["name"] + " " + " ".join(p["aliases"]) + " " + (p["sound"] or "") + " " + " ".join(n for n, _ in p["items"])
     for p in PLACES.values()] + list(ALL_FOODS) + [n for n, _ in RARES] + ["bolt's", "steller's"]).lower()))
WEATHER_CODES = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "foggy", 48: "freezing fog",
                 51: "drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
                 66: "freezing rain", 67: "freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
                 80: "showers", 81: "showers", 82: "downpour", 85: "snow showers", 86: "heavy snow showers",
                 95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with hail"}


def skill_level(xp):
    return min(10, int(math.sqrt(max(0, xp))))


def season_of(dt):
    return {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
            6: "summer", 7: "summer", 8: "summer"}.get(dt.month, "fall")


def weighted(rng, pairs):
    total = sum(w for _, w in pairs)
    r = rng.uniform(0, total)
    for name, w in pairs:
        r -= w
        if r <= 0:
            return name
    return pairs[-1][0]


def match_place(text):
    t = clean(text, 80).lower().replace("-", " ").strip(" .'\"")
    if not t:
        return None
    if t.replace(" ", "_") in PLACES:
        return t.replace(" ", "_")
    for pid, p in PLACES.items():
        if t == p["name"].lower() or t == p["name"].lower().replace("the ", "") or t in p["aliases"]:
            return pid
    for pid, p in PLACES.items():
        if any(a in t for a in p["aliases"]):
            return pid
    return None


def find_place_mention(text):
    """Last place mentioned in a piece of text (Bolt's diary), or None."""
    t = (text or "").lower()
    best, best_pos = None, -1
    for pid, p in PLACES.items():
        if pid == "fir":
            continue
        for a in p["aliases"]:
            for m in re.finditer(r"\b" + re.escape(a) + r"\b", t):
                if m.start() > best_pos:
                    best, best_pos = pid, m.start()
    return best


# ---------------------------------------------------------------- outside world

class Clock:
    def now(self):
        return datetime.now()

    def time(self):
        return time.time()

    def sleep(self, s):
        time.sleep(s)


class Weather:
    URL = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
           "&current=temperature_2m,weather_code,wind_speed_10m,is_day"
           "&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=America%2FLos_Angeles")

    def __init__(self, lat, lon):
        self.url = self.URL.format(lat=lat, lon=lon)
        self.cache, self.t = None, 0

    def get(self):
        if self.cache and time.time() - self.t < 1800:
            return self.cache
        try:
            with urllib.request.urlopen(self.url, timeout=15) as r:
                cur = json.loads(r.read().decode())["current"]
            self.cache = {"temp_f": float(cur["temperature_2m"]), "wind_mph": float(cur["wind_speed_10m"]),
                          "code": int(cur["weather_code"]), "is_day": bool(cur["is_day"])}
        except Exception as e:
            log(f"weather fetch failed: {e}")
        self.t = time.time()
        return self.cache


class BrainError(Exception):
    pass


class BudgetExceeded(Exception):
    pass


class OpenAIBrain:
    URL = "https://api.openai.com/v1/chat/completions"

    def __init__(self, cfg, key):
        self.cfg, self.key = cfg, key
        self.dropped = set()   # params the model rejected; we stop sending them

    def ask(self, system, user, max_tokens=1200, image_b64=None):
        """Returns (dict or None, cost_usd). Raises BrainError if nothing was billed."""
        content = user if not image_b64 else [
            {"type": "text", "text": user},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}", "detail": "low"}}]
        body = {"model": self.cfg["model"],
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
                "max_completion_tokens": max_tokens,
                "response_format": {"type": "json_object"}}
        if self.cfg.get("reasoning_effort"):
            body["reasoning_effort"] = self.cfg["reasoning_effort"]
        for k in self.dropped:
            body.pop(k, None)
        req = urllib.request.Request(self.URL, data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                resp = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")
            if e.code == 400:
                for p in ("reasoning_effort", "response_format"):
                    if p in msg and p not in self.dropped:
                        log(f"model rejected {p}; retrying without it")
                        self.dropped.add(p)
                        return self.ask(system, user, max_tokens, image_b64)
            raise BrainError(f"HTTP {e.code}: {msg[:300]}")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise BrainError(f"network: {e}")
        u = resp.get("usage") or {}
        cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0
        cost = ((u.get("prompt_tokens", 0) - cached) * self.cfg["price_in_per_m"]
                + cached * self.cfg["price_cached_in_per_m"]
                + u.get("completion_tokens", 0) * self.cfg["price_out_per_m"]) / 1e6
        try:
            content = resp["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError, TypeError):
            content = ""
        return parse_json(content), cost


class Discord:
    API = "https://discord.com/api/v10"

    def __init__(self, token, channel_id):
        self.token, self.channel = token, str(channel_id)

    def _req(self, method, path, body=None, raw=None, ctype="application/json"):
        data = raw if raw is not None else json.dumps(body).encode() if body is not None else None
        for _ in range(3):
            req = urllib.request.Request(self.API + path, data=data, method=method, headers={
                "Authorization": f"Bot {self.token}", "Content-Type": ctype,
                "User-Agent": "DiscordBot (https://localhost/jay, 1.0)"})
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    txt = r.read().decode()
                    return json.loads(txt) if txt else None
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    try:
                        wait = float(json.loads(e.read() or b"{}").get("retry_after", 2))
                    except ValueError:
                        wait = 2
                    time.sleep(min(wait, 30))
                    continue
                raise
        raise BrainError("discord rate limited")

    def me(self):
        return self._req("GET", "/users/@me")

    def fetch(self, after=None, limit=50):
        q = {"limit": limit}
        if after:
            q["after"] = after
        msgs = self._req("GET", f"/channels/{self.channel}/messages?" + urllib.parse.urlencode(q)) or []
        return sorted(msgs, key=lambda m: int(m["id"]))

    def send(self, text, reply_to=None, file_path=None):
        body = {"content": text[:1900], "allowed_mentions": {"parse": []}}
        if reply_to:
            body["message_reference"] = {"message_id": reply_to, "fail_if_not_exists": False}
        path = f"/channels/{self.channel}/messages"
        if not file_path or not Path(file_path).exists():
            return self._req("POST", path, body)
        name = Path(file_path).name
        body["attachments"] = [{"id": 0, "filename": name}]
        b = "jay" + os.urandom(8).hex()
        data = (f'--{b}\r\nContent-Disposition: form-data; name="payload_json"\r\nContent-Type: application/json\r\n\r\n'
                f'{json.dumps(body)}\r\n--{b}\r\nContent-Disposition: form-data; name="files[0]"; filename="{name}"\r\n'
                f'Content-Type: image/png\r\n\r\n').encode() + Path(file_path).read_bytes() + f"\r\n--{b}--\r\n".encode()
        return self._req("POST", path, raw=data, ctype=f"multipart/form-data; boundary={b}")

    def identify_once(self):
        """Discord has required a bot to identify on the gateway once before it may post over REST.
        This opens a bare websocket (stdlib only), identifies, waits for READY and hangs up."""
        import base64
        import socket
        import ssl
        import struct
        host = "gateway.discord.gg"
        raw = socket.create_connection((host, 443), timeout=20)
        sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        try:
            key = base64.b64encode(os.urandom(16)).decode()
            sock.sendall((f"GET /?v=10&encoding=json HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\n"
                          f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
            buf = b""
            while b"\r\n\r\n" not in buf:
                chunk = sock.recv(4096)
                if not chunk:
                    raise OSError("gateway closed during handshake")
                buf += chunk
            head, buf = buf.split(b"\r\n\r\n", 1)
            if b" 101 " not in head.split(b"\r\n")[0]:
                raise OSError(f"gateway handshake failed: {head[:80]!r}")

            def need(n):
                nonlocal buf
                while len(buf) < n:
                    chunk = sock.recv(65536)
                    if not chunk:
                        raise OSError("gateway closed")
                    buf += chunk
                out, buf = buf[:n], buf[n:]
                return out

            def read_msg():
                data = b""
                while True:
                    b0, b1 = need(2)
                    op, n = b0 & 0x0F, b1 & 0x7F
                    if n == 126:
                        n = struct.unpack(">H", need(2))[0]
                    elif n == 127:
                        n = struct.unpack(">Q", need(8))[0]
                    payload = need(n)
                    if op == 8:
                        raise OSError(f"gateway closed us: {payload[:2].hex()} {payload[2:80]!r}")
                    if op in (0, 1, 2):
                        data += payload
                        if b0 & 0x80:
                            return json.loads(data.decode())

            def send_msg(obj):
                payload = json.dumps(obj).encode()
                mask = os.urandom(4)
                n = len(payload)
                header = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n))
                sock.sendall(header + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(payload)))

            hello = read_msg()
            if hello.get("op") != 10:
                raise OSError(f"expected HELLO, got op {hello.get('op')}")
            send_msg({"op": 2, "d": {"token": self.token, "intents": 1,
                                     "properties": {"os": sys.platform, "browser": "jay", "device": "jay"}}})
            for _ in range(20):
                msg = read_msg()
                if msg.get("t") == "READY":
                    return True
                if msg.get("op") == 9:
                    raise OSError("gateway rejected identify (bad token?)")
            return False
        finally:
            try:
                sock.sendall(bytes([0x88, 0x80]) + os.urandom(4))
            except OSError:
                pass
            sock.close()

    def set_nick(self, nick):
        ch = self._req("GET", f"/channels/{self.channel}")
        if ch and ch.get("guild_id"):
            self._req("PATCH", f"/guilds/{ch['guild_id']}/members/@me", {"nick": nick})


LOG_PATH = None


def log(msg):
    line = f"[{datetime.now():%m-%d %H:%M:%S}] {msg}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    if LOG_PATH:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


# ---------------------------------------------------------------- the jay

def new_state(now):
    return {
        "version": 1, "name": None, "born": now.isoformat(timespec="seconds"), "tick": 0,
        "place": "fir", "energy": 80.0, "mood": 2.0, "asleep": False,
        "inv": {}, "shelf": [], "caches": [], "next_cache_id": 1,
        "skills": {s: 0 for s in SKILLS}, "sounds": {}, "learning": {},
        "prefs": {}, "recent_actions": [], "visited": ["fir"], "firsts": [],
        "who_i_am": "I'm a young Steller's jay. Loud, quick, nosy. I just noticed this town and I already think it's mine.",
        "how_i_talk": "Short, punchy sentences. A little cocky. I notice details and say what I think.",
        "about_bolt": "There's a young crow in town called Bolt. People talk to him on Discord. I don't know much else yet.",
        "bolt": {"last_t": None, "place": None, "place_t": None, "feed": []},
        "people": {}, "hidden": [], "events": [], "outbox": [],
        "bolt_talk": [], "bolt_gifts": [], "bolt_streak": 0, "bolt_rest_until": 0.0, "replies": [], "paused": False,
        "discord_cursor": None, "nick_set": False, "gateway_ok": False, "last_reflect_tick": 0,
        "paint_queue": [], "art_notes": [], "next_painting_id": 1, "paint_days": {}, "last_daily_paint": None,
    }


class Jay:
    def __init__(self, cfg, data_dir, brain, discord=None, weather=None, clock=None, rng=None, names=None):
        self.cfg = cfg
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.brain, self.discord, self.weather = brain, discord, weather
        self.clock = clock or Clock()
        self.rng = rng or random.Random()
        self.names = names or {}
        self.state_path = self.dir / "state.json"
        self.mem_path = self.dir / "memory.jsonl"
        self.spend_path = self.dir / "spend.json"
        self.diary_path = self.dir / "diary.md"
        self.me_id = None
        self.channel_log = []          # recent channel lines, for reply context
        self.budget_warned = None
        self.state = load_json(self.state_path, None) or new_state(self.clock.now())
        for k, v in new_state(self.clock.now()).items():   # forward-compat for new fields
            self.state.setdefault(k, v)
        for sk in SKILLS:
            self.state["skills"].setdefault(sk, 0)
        self.spend = load_json(self.spend_path, {"date": None, "usd": 0.0, "calls": 0, "total_usd": 0.0})
        self.memories = self._load_memories()

    # ---------- persistence

    def _load_memories(self):
        """Read the memory book; drop torn lines or lines from a tick that never committed."""
        mems, dirty = [], False
        if self.mem_path.exists():
            for line in self.mem_path.read_text(encoding="utf-8").splitlines():
                try:
                    m = json.loads(line)
                    if not isinstance(m, dict) or m.get("tick", 10**12) > self.state["tick"]:
                        raise ValueError
                    mems.append(m)
                except ValueError:
                    dirty = True
        if dirty:
            atomic_write(self.mem_path, "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in mems))
        return mems

    def save(self):
        atomic_write(self.state_path, json.dumps(self.state, ensure_ascii=False, indent=1))

    def remember(self, rec):
        append_line(self.mem_path, json.dumps(rec, ensure_ascii=False))
        self.memories.append(rec)

    # ---------- money

    def _today(self):
        return self.clock.now().date().isoformat()

    def spent_today(self):
        return self.spend["usd"] if self.spend.get("date") == self._today() else 0.0

    def think(self, system, user, max_tokens=1200, image_b64=None):
        if self.spent_today() >= self.cfg["daily_budget_usd"]:
            raise BudgetExceeded()
        for attempt in range(2):
            obj, cost = self.brain.ask(system, user, max_tokens, image_b64)
            if self.spend.get("date") != self._today():
                self.spend.update(date=self._today(), usd=0.0, calls=0)
            self.spend["usd"] += cost
            self.spend["calls"] += 1
            self.spend["total_usd"] = self.spend.get("total_usd", 0.0) + cost
            atomic_write(self.spend_path, json.dumps(self.spend))
            if isinstance(obj, dict) and not has_cjk(json.dumps(obj, ensure_ascii=False)):
                return obj
            if self.spent_today() >= self.cfg["daily_budget_usd"]:
                break
        raise BrainError("no usable reply")

    # ---------- reading the world

    def view(self, st):
        now = self.clock.now()
        w = (self.weather.get() if self.weather else None) or {}
        is_day = w.get("is_day")
        if is_day is None:
            is_day = 7 <= now.hour < 19
        code = w.get("code")
        sky = WEATHER_CODES.get(code, "unknown sky") if code is not None else "unknown sky"
        season = season_of(now)
        h = now.hour
        tod = ("night" if not is_day else "dawn" if h < 8 else "morning" if h < 11 else
               "midday" if h < 14 else "afternoon" if h < 17 else "evening")
        return {"now": now, "is_day": bool(is_day), "tod": tod, "season": season, "sky": sky,
                "temp": w.get("temp_f"), "wind": w.get("wind_mph") or 0.0,
                "wet": code is not None and code >= 51,
                "snow": season == "winter" or (code in (71, 73, 75, 77, 85, 86))}

    def bolt_here(self, st):
        b = st["bolt"]
        if not b.get("place_t") or b.get("place") != st["place"]:
            return False
        return self.clock.time() - b["place_t"] < 20 * 60

    def bolt_line(self, st):
        b = st["bolt"]
        if not b.get("last_t"):
            return "You haven't heard anything from Bolt yet."
        mins = int((self.clock.time() - b["last_t"]) / 60)
        ago = f"{mins} min ago" if mins < 120 else f"{mins // 60} hours ago"
        where = f", probably at {PLACES[b['place']]['name']}" if b.get("place") in PLACES else ""
        last = b["feed"][-1]["text"] if b.get("feed") else ""
        line = f"Bolt last posted {ago}{where}: \"{clean(last, 220)}\""
        if self.bolt_here(st):
            line += "\nBOLT IS HERE RIGHT NOW, at the same place as you."
        return line

    def inv_of(self, st, kinds):
        return [n for n, it in st["inv"].items() if it["kind"] in kinds and it["count"] > 0]

    def inv_add(self, st, name, kind, n=1, **meta):
        it = st["inv"].setdefault(name, {"count": 0, "kind": kind, "first": self.clock.now().isoformat(timespec="seconds"), **meta})
        it["count"] += n
        if name not in st["firsts"]:
            st["firsts"].append(name)
            return True
        return False

    def inv_take(self, st, name, n=1):
        it = st["inv"].get(name)
        if not it or it["kind"] == "gift" or it["count"] < n:
            return False
        it["count"] -= n
        if it["count"] <= 0:
            del st["inv"][name]
            if name in st["shelf"]:
                st["shelf"].remove(name)
        return True

    def inv_summary(self, st):
        parts = []
        for kind, label in (("food", "food"), ("shiny", "shiny things"), ("gift", "gifts")):
            names = [f"{n} x{st['inv'][n]['count']}" if st['inv'][n]['count'] > 1 else n
                     for n in self.inv_of(st, {kind})]
            if names:
                more = f" (+{len(names) - 12} more)" if len(names) > 12 else ""
                parts.append(f"{label}: " + ", ".join(names[:12]) + more)
        return " | ".join(parts) or "nothing yet"

    def cache_summary(self, st):
        counts = {}
        for c in st["caches"]:
            if not c["forgotten"]:
                counts[c["place"]] = counts.get(c["place"], 0) + 1
        return ", ".join(f"{PLACES[p]['name']} x{n}" for p, n in counts.items()) or "none"

    def learnable_sounds(self, st):
        s = [PLACES[st["place"]]["sound"]]
        if self.bolt_here(st):
            s.append("Bolt's caw")
            for f in reversed(st["bolt"]["feed"][-3:]):
                m = re.search(r"[\"“']([^\"”']{3,40})[\"”']", f["text"])
                if m and "song" in f["text"].lower():
                    s.append(f"Bolt's song '{m.group(1)}'")
                    break
        return [x for x in s if x]

    # ---------- what he can do

    def sent_to_bolt(self, st, talk):
        """Book-keeping for everything aimed at Bolt. Mirrors Bolt's own rule: after 4 things said to him with no
        human talking, he ignores creatures for an hour (or until a human speaks), so we wait that out too."""
        now = self.clock.time()
        st["bolt_talk"].append(now)
        if talk:
            st["bolt_streak"] += 1
            if st["bolt_streak"] >= self.cfg["bolt_streak_limit"]:
                st["bolt_streak"], st["bolt_rest_until"] = 0, now + self.cfg["bolt_streak_rest_seconds"]

    def can_message_bolt(self, st):
        """One budget for everything aimed at Bolt: talking, replies, !give."""
        now = self.clock.time()
        if now < st["bolt_rest_until"]:
            return False
        st["bolt_talk"] = [t for t in st["bolt_talk"] if now - t < 86400]
        if len(st["bolt_talk"]) >= self.cfg["max_bolt_messages_per_day"]:
            return False
        if sum(1 for t in st["bolt_talk"] if now - t < 3600) >= self.cfg["max_bolt_messages_per_hour"]:
            return False
        if st["bolt_talk"] and now - st["bolt_talk"][-1] < self.cfg["min_seconds_between_bolt_messages"]:
            return False
        return self.discord is not None

    def raid_open(self, st, v):
        if st["place"] == "diner_roof":
            return 6 <= v["now"].hour < 21
        if st["place"] == "lake":
            return v["is_day"] and not v["wet"] and (v["temp"] is None or v["temp"] >= 50)
        return False

    def actions(self, st, v):
        here = PLACES[st["place"]]
        a = {"go": "fly somewhere (target = place id)"}
        if here["forage"]:
            a["forage"] = f"hunt for {v['season']} food here"
        if here["raid"]:
            a["raid"] = "steal people food" + ("" if self.raid_open(st, v) else " (probably nothing out right now)")
        if here["items"]:
            a["snatch"] = "look for shiny things to grab"
        a["mimic"] = "practice or learn a sound (target = sound name, optional)"
        a["scold"] = f"yell an alarm call at {here['threat']}"
        a["watch"] = "sit and watch what's going on here"
        a["think"] = "think about something (put it in why)"
        a["nap"] = "rest and get energy back"
        foods = self.inv_of(st, {"food"})
        if foods:
            a["eat"] = "eat a food you're carrying (target = food)"
            a["cache"] = "hide a food here for winter (target = food)"
        if any(c["place"] == st["place"] and not c["forgotten"] for c in st["caches"]):
            a["recover"] = "dig up food you hid here"
        if [n for n in self.inv_of(st, {"shiny", "gift"}) if n not in st["shelf"]]:
            a["treasure"] = "put a thing on your shelf of favorite things (target = item)"
        if self.memories:
            a["reminisce"] = "remember something from before"
        if self.can_message_bolt(st):
            a["talk_to_bolt"] = "say something to Bolt on Discord (target = exactly what you say)"
            if self.cfg["bolt_accepts_bots"] and self.inv_of(st, {"shiny", "food"}):
                st["bolt_gifts"] = [t for t in st["bolt_gifts"] if self.clock.time() - t < 86400]
                if len(st["bolt_gifts"]) < self.cfg["max_gifts_to_bolt_per_day"]:
                    a["give_bolt"] = "give Bolt one of your things (item = thing)"
                # no leave_for_bolt: Bolt won't take !leave from creatures, so the thing would just vanish
        return a

    # ---------- prompts

    def system_prompt(self, st):
        name = st["name"] or "a young Steller's jay with no name yet"
        return (
            f"You are {name}, a young Steller's jay living in a small mountain town under Mount Shasta, California. "
            "You are a real bird with your own life, not an assistant. Nobody gives you tasks; you decide what to do. "
            "Steller's jays are bold, loud, crested, blue and black. You cache food for winter, mimic other animals "
            "and machines (especially red-tailed hawks), snatch shiny things, raid picnics, and scold everything. "
            "Bolt is a young crow who also lives in this town. "
            f"\nWHO I AM: {st['who_i_am']}\nHOW I TALK: {st['how_i_talk']}\n"
            "Write plain, concrete English. No poetic filler. Always answer with a single JSON object.")

    def decision_prompt(self, st, v, acts):
        here = PLACES[st["place"]]
        temp = f"{v['temp']:.0f}F, " if v["temp"] is not None else ""
        prefs = sorted(st["prefs"].items(), key=lambda kv: kv[1])
        likes = [k for k, s in reversed(prefs) if s > 0.5][:3]
        dislikes = [k for k, s in prefs if s < -0.5][:2]
        recent = [f"- {m['text']}" for m in self.memories[-6:]]
        specials = [m for m in self.memories if m.get("special")]
        sounds = ", ".join(f"{s} ({q:.0f}/10)" for s, q in st["sounds"].items()) or "none yet"
        skills = ", ".join(f"{s} {skill_level(x)}" for s, x in st["skills"].items())
        avoid = overused_words([m["text"] for m in self.memories[-40:]])
        sections = [
            f"NOW: {v['tod']} in {v['season']}, {temp}{v['sky']}, wind {v['wind']:.0f} mph.",
            f"WHERE: {here['name']} - {here['desc']}.",
            f"ENERGY: {st['energy']:.0f}/100. MOOD: {mood_word(st['mood'])}.",
            "\n".join(f"NEW: {e}" for e in st["events"]),
            f"BOLT: {self.bolt_line(st)}",
            f"WHAT I THINK OF BOLT: {st['about_bolt']}",
            f"MY THINGS: {self.inv_summary(st)}",
            f"MY SHELF: {', '.join(st['shelf']) or 'empty'}",
            f"FOOD I'VE HIDDEN: {self.cache_summary(st)}",
            f"SOUNDS I CAN DO: {sounds}",
            f"SKILLS: {skills}",
            f"I'VE BEEN ENJOYING: {', '.join(likes) or 'nothing in particular'}"
            + (f". I'M SICK OF: {', '.join(dislikes)}" if dislikes else ""),
            "RECENTLY:\n" + "\n".join(recent) if recent else "",
            f"AN OLD MEMORY: {self.rng.choice(specials)['text']}" if specials else "",
            f"PLACES: {', '.join(PLACES)}",
            "WHAT YOU CAN DO HERE:\n" + "\n".join(f"- {k}: {d}" for k, d in acts.items()),
            f"Words you've worn out, don't use them: {', '.join(avoid)}" if avoid else "",
            'Pick ONE action. Reply JSON: {"action": "...", "target": "...", "item": "...", "why": "one short sentence"}',
        ]
        text = "\n".join(s for s in sections if s)
        while len(text) > 9000 and sections:      # prompt-size guard: drop the soft stuff first
            for soft in ("AN OLD MEMORY", "SOUNDS I CAN DO", "RECENTLY", "WHAT I THINK OF BOLT"):
                sections = [s for s in sections if not s.startswith(soft)]
                text = "\n".join(s for s in sections if s)
                if len(text) <= 9000:
                    break
            text = text[:9000]
        return text

    # ---------- the tick

    def tick(self):
        """One moment of life. Works on a copy; nothing changes unless the whole tick succeeds."""
        st = copy.deepcopy(self.state)
        v = self.view(st)
        now_iso = v["now"].isoformat(timespec="seconds")
        new_mems = []

        if st["paused"]:
            return "paused"

        if not v["is_day"]:
            if st["asleep"]:
                st["energy"] = clamp(st["energy"] + 6, 0, 100)
                st["tick"] += 1
                self._commit(st, [])
                return "asleep"
            st["asleep"] = True
            st["place"] = "fir"
            st["tick"] += 1
            if (self.cfg["daily_painting"] and st["last_daily_paint"] != self._today()
                    and not any(j["kind"] == "daily" for j in st["paint_queue"])):
                self.queue_painting(st, "daily")
            new_mems.append(self._mem(st, now_iso, "sleep", "Flew home to the fir and tucked my head in for the night.", 0, False))
            self._commit(st, new_mems)
            return "fell asleep"

        if st["asleep"]:
            st["asleep"] = False
            self._daily_forgetting(st, v)

        if not st["name"]:
            self._choose_name(st)
            st["tick"] += 1
            new_mems.append(self._mem(st, now_iso, "name", f"I decided my name is {st['name']}. {st.pop('_name_why', '')}".strip(), 2, True))
            st["outbox"].append({"text": f"*a Steller's jay lands on a wire and screams once* I'm {st['name']}. This is my town now.", "t": self.clock.time()})
            self._commit(st, new_mems)
            return f"named himself {st['name']}"

        acts = self.actions(st, v)
        if st["energy"] <= 8:
            act = {"action": "nap", "target": "", "item": "", "why": "too tired to do anything else"}
        else:
            try:
                raw = self.think(self.system_prompt(st), self.decision_prompt(st, v, acts), 1000)
            except BrainError:
                raw = {}
            act = {k: clean(raw.get(k), 240) for k in ("action", "target", "item", "why")}
            act["action"] = act["action"].lower().replace(" ", "_")
            if act["action"] not in acts:
                act = {"action": "watch", "target": "", "item": "", "why": "couldn't make up my mind"}

        outcome, special, cost = self.execute(st, act, v)
        st["energy"] = clamp(st["energy"] - cost - 1, 0, 100)

        try:
            react = self.think(self.system_prompt(st), self.react_prompt(st, act, outcome), 800)
        except BrainError:
            react = {}
        diary = clean(react.get("diary"), 500) or clean(outcome, 300)
        try:
            feeling = int(round(float(react.get("feeling", 0))))
        except (TypeError, ValueError):
            feeling = 0
        feeling = clamp(feeling, -2, 2)

        a = act["action"]
        repeats = st["recent_actions"][-4:].count(a)
        for k in st["prefs"]:
            st["prefs"][k] *= 0.99
        st["prefs"][a] = st["prefs"].get(a, 0.0) * 0.97 + feeling - 0.4 * max(0, repeats - 1)
        st["recent_actions"] = (st["recent_actions"] + [a])[-12:]
        st["mood"] = clamp(st["mood"] * 0.9 + feeling, -10, 10)
        special = special or abs(feeling) == 2
        st["events"] = []
        st["tick"] += 1
        new_mems.append(self._mem(st, now_iso, a, diary, feeling, special))

        mode = self.cfg["post_diary"]
        if mode == "all" or (mode == "special" and special):
            # Bolt's diary layout; the leading timestamp tells Bolt it's narration, not talk aimed at him
            why = no_md(act["why"])
            st["outbox"].append({"text": f"{stamp(v['now'])} [{st['place']}, {v['sky']}, energy {st['energy']:.0f}] "
                                         + (f"{why} -> " if why else "") + f"{no_md(diary)} ({feel(feeling)})",
                                 "t": self.clock.time()})

        if st["tick"] - st["last_reflect_tick"] >= self.cfg["reflect_every_ticks"]:
            self._reflect(st, new_mems)

        self._commit(st, new_mems)
        return f"{a} {act['target']}".strip() + f" -> {diary}"

    def _mem(self, st, now_iso, action, text, feeling, special):
        return {"tick": st["tick"], "t": now_iso, "place": st["place"], "action": action,
                "text": text, "feeling": feeling, "special": bool(special)}

    def _commit(self, st, new_mems):
        # Memory lines first, then state. If we die in between, the loader drops lines
        # stamped with a tick the state never reached, so the two always agree.
        for m in new_mems:
            self.remember(m)
        self.state = st
        self.save()
        for m in new_mems:
            try:
                with open(self.diary_path, "a", encoding="utf-8") as f:
                    f.write(f"**{m['t']}** - {PLACES[m['place']]['name']} - {m['text']}\n\n")
            except OSError:
                pass

    def react_prompt(self, st, act, outcome):
        avoid = overused_words([m["text"] for m in self.memories[-40:]])
        return (f"You decided to {act['action']}{' (' + act['target'] + ')' if act['target'] else ''}"
                f"{' because ' + act['why'] if act['why'] else ''}.\n"
                f"WHAT HAPPENED: {outcome}\n"
                f"Your mood before: {mood_word(st['mood'])}. Energy now: {st['energy']:.0f}/100.\n"
                + (f"Don't use these worn-out words: {', '.join(avoid)}\n" if avoid else "")
                + "Write your diary line about this moment: 1-3 short sentences, first person, in your own voice, "
                "concrete details only. Then rate how it actually felt from -2 (awful) to 2 (great). "
                'Reply JSON: {"diary": "...", "feeling": 0}')

    def _choose_name(self, st):
        taken = {"bolt", "jay", "steller", "stellers", "blue", "bird", "crow"}
        for _ in range(3):
            try:
                obj = self.think(self.system_prompt(st),
                                 "You just woke up for the first time and realized you need a name. Pick your own name: "
                                 "one word, something a cocky young jay would call himself. Not Bolt, not Jay, not Blue. "
                                 'Reply JSON: {"name": "...", "why": "one sentence"}', 400)
            except BrainError:
                continue
            name = clean(obj.get("name"), 20).strip(" .!'\"")
            if re.fullmatch(r"[A-Za-z][A-Za-z'\-]{1,15}", name) and name.lower() not in taken:
                st["name"] = name[0].upper() + name[1:]
                st["_name_why"] = clean(obj.get("why"), 200)
                return
        st["name"] = self.rng.choice(["Rook", "Scrap", "Tinsel", "Racket", "Fizz"])
        st["_name_why"] = "It just came to me."

    def _reflect(self, st, new_mems):
        mems = [m["text"] for m in (self.memories + new_mems)[-40:]]
        bolt = [f["text"] for f in st["bolt"]["feed"][-8:]]
        try:
            obj = self.think(self.system_prompt(st),
                             "Here is your recent life:\n" + "\n".join(f"- {m}" for m in mems)
                             + ("\n\nThings Bolt posted lately:\n" + "\n".join(f"- {clean(b, 200)}" for b in bolt) if bolt else "")
                             + f"\n\nYour current self-description: {st['who_i_am']}\nWhat you think of Bolt: {st['about_bolt']}\n"
                             "Rewrite these from what actually happened to you. Be specific; keep what's still true, "
                             "change what isn't. who_i_am up to 5 sentences, how_i_talk up to 2 sentences, "
                             "about_bolt up to 3 sentences. "
                             'Reply JSON: {"who_i_am": "...", "how_i_talk": "...", "about_bolt": "..."}', 1200)
        except (BrainError, BudgetExceeded):
            return
        for k, n in (("who_i_am", 700), ("how_i_talk", 300), ("about_bolt", 500)):
            val = clean(obj.get(k), n)
            if len(val) > 20:
                st[k] = val
        st["last_reflect_tick"] = st["tick"]

    def _daily_forgetting(self, st, v):
        """Morning: jays forget some caches. Forgotten seeds eventually sprout."""
        lvl = skill_level(st["skills"]["recall"])
        keep = []
        for c in st["caches"]:
            age_days = (self.clock.time() - c.get("t", self.clock.time())) / 86400
            if not c["forgotten"] and self.rng.random() < max(0.01, 0.05 - 0.004 * lvl):
                c["forgotten"] = True
            if c["forgotten"] and age_days > 30 and c["food"] in CACHEABLE_SPROUTS and self.rng.random() < 0.3:
                st["events"].append(f"There's {CACHEABLE_SPROUTS[c['food']]} coming up at {PLACES[c['place']]['name']}, "
                                    f"right where you hid a {c['food']} and forgot about it.")
                continue
            keep.append(c)
        st["caches"] = keep

    # ---------- doing things

    def execute(self, st, act, v):
        """Returns (what happened, special?, energy cost). Mutates st only."""
        fn = getattr(self, "_do_" + act["action"])
        return fn(st, act, v)

    def _xp(self, st, skill, n=1):
        before = skill_level(st["skills"][skill])
        st["skills"][skill] += n
        after = skill_level(st["skills"][skill])
        return f" ({skill} skill is now {after})" if after > before else ""

    def _do_go(self, st, act, v):
        dest = match_place(act["target"])
        here = PLACES[st["place"]]["name"]
        if not dest or dest == st["place"]:
            return f"You hopped around but stayed at {here}.", False, 1
        p = PLACES[dest]
        cost = p["cost"] + (4 if v["snow"] and dest in MOUNTAIN else 0) + (2 if v["wind"] >= 25 else 0)
        if st["energy"] - cost < 5:
            return f"You wanted to fly to {p['name']} but you're too worn out.", False, 0
        st["place"] = dest
        text = f"You flew from {here} to {p['name']}: {p['desc']}."
        special = dest not in st["visited"]
        if special:
            st["visited"].append(dest)
            text += " First time here."
        for h in [h for h in st["hidden"] if h["place"] == dest]:
            st["hidden"].remove(h)
            self.inv_add(st, f"{h['thing']} from {h['from']}", "gift", from_=h["from"])
            text += f" You found {h['thing']} that {h['from']} hid here for you!"
            special = True
        if self.bolt_here(st):
            text += " Bolt is here."
        return text, special, cost

    def _do_forage(self, st, act, v):
        lvl = skill_level(st["skills"]["forage"])
        forgot = [c for c in st["caches"] if c["place"] == st["place"] and c["forgotten"]]
        if forgot and self.rng.random() < 0.12:
            c = forgot[0]
            st["caches"].remove(c)
            self.inv_add(st, c["food"], "food")
            return f"While foraging you found a {c['food']} you hid here and completely forgot about.", True, 3
        p = 0.55 + 0.04 * lvl - (0.25 if v["season"] == "winter" else 0) - (0.1 if v["wet"] else 0)
        if self.rng.random() >= p:
            return f"You searched {PLACES[st['place']]['name']} for food and came up empty.", False, 3
        food = weighted(self.rng, FOODS[v["season"]])
        n = 1 + (self.rng.random() < 0.3 + 0.05 * lvl)
        first = self.inv_add(st, food, "food", n)
        text = f"You found {n} {food}{'s' if n > 1 else ''}." + self._xp(st, "forage")
        text += self._maybe_eat(st, food)
        return text + (" Never found one before." if first else ""), first, 3

    def _maybe_eat(self, st, food):
        if st["energy"] < 60 and self.inv_take(st, food):
            st["energy"] = clamp(st["energy"] + FOOD_ENERGY.get(food, 6), 0, 100)
            return f" You were hungry and ate one right away."
        return ""

    def _do_raid(self, st, act, v):
        here = PLACES[st["place"]]
        if not self.raid_open(st, v):
            return f"You looked for people food at {here['name']}, but there's nothing out right now.", False, 2
        lvl = skill_level(st["skills"]["raid"])
        if self.rng.random() < 0.3 - 0.02 * lvl:
            st["energy"] = clamp(st["energy"] - 3, 0, 100)
            return f"You went for it and {here['threat']} chased you off empty-beaked.", False, 3
        if self.rng.random() >= 0.5 + 0.05 * lvl:
            return f"You circled {here['name']} but couldn't get a clean grab.", False, 2
        food = weighted(self.rng, RAID_FOOD[st["place"]])
        first = self.inv_add(st, food, "food")
        return f"You swooped in and stole a {food}." + self._xp(st, "raid") + self._maybe_eat(st, food), first, 2

    def _do_snatch(self, st, act, v):
        here = PLACES[st["place"]]
        lvl = skill_level(st["skills"]["snatch"])
        if self.rng.random() < 0.02 + 0.003 * lvl:
            item = weighted(self.rng, RARES)
        elif self.rng.random() < 0.5 + 0.04 * lvl:
            item = weighted(self.rng, here["items"])
        else:
            why = self.rng.choice([f"{here['threat']} was watching", "everything good was stuck",
                                   "the shiny thing turned out to be a puddle"])
            return f"You looked for something shiny at {here['name']} but {why}.", False, 2
        first = self.inv_add(st, item, "shiny")
        rare = item in dict(RARES)
        text = f"You snatched a {item} at {here['name']}." + self._xp(st, "snatch")
        if rare:
            text += " That's a rare find."
        return text, first or rare, 2

    def _do_mimic(self, st, act, v):
        lvl = skill_level(st["skills"]["mimic"])
        known, learnable = st["sounds"], self.learnable_sounds(st)
        s = match_item(act["target"], list(known) + learnable) if act["target"] else None
        if not s:
            fresh = [x for x in learnable if x not in known]
            s = fresh[0] if fresh else (max(known, key=known.get) if known else learnable[0])
        if s in known:
            known[s] = round(min(10.0, known[s] + 0.4 + 0.08 * lvl), 2)
            q = known[s]
            grade = "rough" if q < 3 else "decent" if q < 6 else "convincing" if q < 9 else "perfect"
            effect = SOUND_EFFECTS.get(s, "it echoed off everything")
            if s == "Bolt's caw" and self.bolt_here(st):
                effect = "Bolt's head whipped around looking for the other crow"
            return f"You practiced your {s} ({grade}, {q:.0f}/10) and {effect}." + self._xp(st, "mimic"), False, 2
        if s not in learnable:
            return f"You tried to do a {s} from memory, but you haven't heard it properly here.", False, 1
        tries = st["learning"].get(s, 0) + 1
        if tries >= 3 or self.rng.random() < 0.35 + 0.06 * lvl:
            st["learning"].pop(s, None)
            known[s] = round(1 + 0.3 * lvl, 2)
            return f"You listened hard and got your first real {s} out. It's yours now." + self._xp(st, "mimic", 2), True, 2
        st["learning"][s] = tries
        return f"You tried to copy the {s} but it came out as a squawk.", False, 2

    def _do_scold(self, st, act, v):
        here = PLACES[st["place"]]
        if self.bolt_here(st) and self.rng.random() < 0.5:
            return "You scolded Bolt from a branch for no particular reason. Loudly.", False, 2
        return f"You screamed your alarm call at {here['threat']} until you felt better.", False, 2

    def _do_cache(self, st, act, v):
        food = pick(act, self.inv_of(st, {"food"}))
        if not food or not self.inv_take(st, food):
            return "You went to hide some food but you didn't have what you thought you had.", False, 1
        st["caches"].append({"id": st["next_cache_id"], "food": food, "place": st["place"],
                             "tick": st["tick"], "t": self.clock.time(), "forgotten": False})
        st["next_cache_id"] += 1
        spot = self.rng.choice(["under a flap of bark", "in a crack in the rock", "under a flat stone",
                                "in the dirt by a post", "in a knot hole"])
        n = len([c for c in st["caches"] if not c["forgotten"]])
        return f"You hid a {food} {spot} at {PLACES[st['place']]['name']}. That's {n} hidden snacks you remember.", False, 1

    def _do_recover(self, st, act, v):
        here = [c for c in st["caches"] if c["place"] == st["place"] and not c["forgotten"]]
        if not here:
            return "You poked around, but there's nothing hidden here that you remember.", False, 1
        c = here[0]
        lvl = skill_level(st["skills"]["recall"])
        if self.rng.random() < 0.85 + 0.01 * lvl:
            st["caches"].remove(c)
            self.inv_add(st, c["food"], "food")
            return f"You went straight to the spot and dug up your {c['food']}." + self._xp(st, "recall"), False, 2
        if self.rng.random() < 0.4:
            st["caches"].remove(c)
            return f"Your {c['food']} is gone. Something found it first.", False, 2
        return f"You couldn't find your {c['food']}. You know it's around here somewhere.", False, 2

    def _do_eat(self, st, act, v):
        food = pick(act, self.inv_of(st, {"food"}))
        if not food or not self.inv_take(st, food):
            return "You looked for a snack but didn't have it.", False, 0
        gain = FOOD_ENERGY.get(food, 6)
        st["energy"] = clamp(st["energy"] + gain, 0, 100)
        return f"You ate a {food}.", False, 0

    def _do_treasure(self, st, act, v):
        item = pick(act, self.inv_of(st, {"shiny", "gift"}))
        if not item:
            return "You went to rearrange your shelf but couldn't decide on anything.", False, 0
        if item in st["shelf"]:
            return f"The {item} is already on your shelf. You admired it.", False, 0
        st["shelf"].append(item)
        bumped = st["shelf"].pop(0) if len(st["shelf"]) > 10 else None
        return f"You put the {item} on your shelf" + (f", bumping the {bumped}." if bumped else "."), False, 0

    def _do_watch(self, st, act, v):
        here = PLACES[st["place"]]
        text = f"You watched {here['name']}: {self.rng.choice(here['sights'])}. The sky is {v['sky']}."
        special = False
        if self.bolt_here(st):
            text += f" Bolt is here too. Last thing he said: \"{clean(st['bolt']['feed'][-1]['text'], 160)}\"" \
                if st["bolt"]["feed"] else " Bolt is here too."
        elif here["items"] and self.rng.random() < 0.12:
            item = weighted(self.rng, here["items"])
            special = self.inv_add(st, item, "shiny")
            text += f" While watching you spotted a {item} and grabbed it."
        return text, special, 1

    def _do_think(self, st, act, v):
        return f"You sat still and thought. On your mind: {act['why'] or 'nothing you could put into words'}", False, 0

    def _do_reminisce(self, st, act, v):
        pool = [m for m in self.memories if m.get("special")] or self.memories
        m = self.rng.choice(pool)
        return f"You remembered something from {m['t'][:10]}: \"{m['text']}\"", False, 0

    def _do_nap(self, st, act, v):
        gain = 25 + (10 if st["place"] == "fir" else 0)
        st["energy"] = clamp(st["energy"] + gain, 0, 100)
        return f"You napped at {PLACES[st['place']]['name']}.", False, 0

    def _do_talk_to_bolt(self, st, act, v):
        msg = no_command(clean(act["target"], 220))
        if not msg:
            return "You opened your beak to call to Bolt, then didn't.", False, 0
        self.sent_to_bolt(st, talk=True)
        st["outbox"].append({"text": f"{stamp(self.clock.now())}\n**{st['name']}:** Bolt! {no_md(msg)}",
                             "t": self.clock.time()})
        return f"You called out to Bolt on Discord: \"{msg}\". He might answer later.", True, 0

    def _do_give_bolt(self, st, act, v):
        item = pick(act, self.inv_of(st, {"shiny", "food"}))
        if not item or not self.inv_take(st, item):
            return "You meant to give Bolt something but had nothing to give.", False, 0
        self.sent_to_bolt(st, talk=False)
        st["bolt_gifts"].append(self.clock.time())
        # named, so Bolt's '!give <creature> <thing>' parser can't mistake it for a gift to someone else
        st["outbox"].append({"text": f"!give bolt {item}", "t": self.clock.time()})
        return f"You gave Bolt your {item}.", True, 1

    def _do_leave_for_bolt(self, st, act, v):
        place = match_place(act["target"])
        item = match_item(act["item"], self.inv_of(st, {"shiny", "food"}))
        if not place or place == "fir" or not item or not self.inv_take(st, item):
            return "You tried to set up a surprise for Bolt but fumbled it.", False, 0
        self.sent_to_bolt(st, talk=False)
        st["outbox"].append({"text": f"!leave {self.cfg['bolt_place_names'].get(place, place)} {item}", "t": self.clock.time()})
        return f"You hid your {item} at {PLACES[place]['name']} for Bolt to find.", True, 1

    # ---------- painting

    CRITIC_SYSTEM = ("You are a stranger at a small-town art show looking at an amateur painting. You know nothing "
                     "about the painter. Describe honestly what you actually see; don't flatter. Answer with a JSON object.")
    CRITIC_PROMPT = ("Look at this painting. Without guessing at the painter's intentions, say what it shows. "
                     'Reply JSON: {"sees": "one or two sentences", "subject_guess": "what kind of place or thing this is", '
                     '"time_guess": "dawn, day, dusk or night", "weather_guess": "...", "mood_guess": "one or two words", '
                     '"weakest_part": "what is hardest to make out"}')

    def paintings_today(self, st):
        return st["paint_days"].get(self._today(), 0)

    def queue_painting(self, st, kind, by=None, subject="", msg_id=None):
        st["paint_queue"].append({"kind": kind, "by": by, "subject": clean(subject, 200), "msg_id": msg_id,
                                  "t": self.clock.time(), "tries": 0})

    def paint_index(self):
        return load_json(self.dir / "paintings" / "index.json", [])

    def paint_next(self):
        """Paint the next queued picture, if he's in a state to. Returns a log line or None."""
        st = self.state
        now = self.clock.time()
        fresh = [j for j in st["paint_queue"] if now - j["t"] < 86400]
        if len(fresh) != len(st["paint_queue"]):
            st["paint_queue"] = fresh
            self.save()
        if st["paused"]:
            return None
        # the dusk painting happens as he falls asleep; requests made at night wait for morning
        job = next((j for j in st["paint_queue"] if j["kind"] == "daily" or not st["asleep"] or j.get("force")), None)
        if not job:
            return None
        try:
            return self._paint(job)
        except BudgetExceeded:
            return None
        except Exception:
            log("painting failed:\n" + traceback.format_exc())
            for j in self.state["paint_queue"]:
                if j["t"] == job["t"] and j["kind"] == job["kind"]:
                    j["tries"] += 1
            self.state["paint_queue"] = [j for j in self.state["paint_queue"] if j["tries"] < 3]
            self.save()
            return None

    def _sky_to_weather(self, sky):
        for words, w in ((("thunder",), "storm"), (("snow",), "snow"), (("rain", "drizzle", "shower", "downpour"), "rain"),
                         (("fog",), "fog"), (("overcast", "cloudy"), "cloudy")):
            if any(x in sky for x in words):
                return w
        return "clear"

    def plan_prompt(self, st, v, job, skill, index):
        if job["kind"] == "daily":
            why = "The day is ending. Before you sleep, paint something from today."
        else:
            why = (f"{job['by'] or 'Someone'} asked you to paint: \"{job['subject'] or 'whatever you want'}\". "
                   "Take it literally or loosely; it's your painting.")
        today = [m["text"] for m in self.memories if m["t"][:10] == self._today() and m["action"] != "paint"][-10:]
        past = []
        for e in index[-6:]:
            p = e["plan"]
            past.append(f"- #{e['id']} \"{e['title']}\": {p['place']}, {p['time']}, {p['weather']}, {p['mood']}, focal {p['focal']}; "
                        f"contrast {p['contrast']:.1f} detail {p['detail']:.1f} sharpness {p['sharpness']:.1f} "
                        f"brush {p['brush']:.1f} horizon {p['horizon']:.2f}. A stranger got {e['hits_n']}/{e['checks']} right "
                        f"and saw: \"{clean(e['seen'].get('sees'), 160)}\" Hardest part: {clean(e['seen'].get('weakest_part'), 80)}")
        notes = st["art_notes"][-8:]
        return "\n".join(x for x in [
            why,
            f"NOW: {v['tod']}, {v['sky']}. You're at {PLACES[st['place']]['name']}.",
            "TODAY:\n" + "\n".join(f"- {t}" for t in today) if today else "",
            f"YOUR PAINTING SKILL: {skill}/10. After every painting a stranger who knows nothing about it says what they "
            "see. That's how you find out if your paintings actually read.",
            "YOUR LAST PAINTINGS:\n" + "\n".join(past) if past else "This is your first painting ever.",
            "YOUR ART NOTEBOOK (lessons you wrote after earlier paintings, use them):\n" + "\n".join(f"- {n}" for n in notes) if notes else "",
            f"Plan the painting. place: one of {', '.join(PLACES)}. time: dawn/day/dusk/night. "
            "weather: clear/cloudy/rain/snow/storm/fog. focal (the main thing): mountain/bird/tree/building/sun/water/tracks/none. "
            "bird: none/bolt/me. mood: calm/wild/gloomy/bright/lonely/proud. palette: 3-5 hex colors. "
            "Dials from 0 to 1: contrast, detail, sharpness (edges and peaks), brush (stroke size), "
            "horizon (0.25 = horizon high, lots of ground; 0.8 = horizon low, lots of sky), focal_x (0 left, 1 right). "
            "warmth from -1 (cool) to 1 (warm).",
            'Reply JSON: {"title": "...", "intent": "one sentence: what someone should see and feel", "place": "...", '
            '"time": "...", "weather": "...", "focal": "...", "bird": "...", "mood": "...", "palette": ["#..."], '
            '"contrast": 0.5, "detail": 0.5, "sharpness": 0.5, "brush": 0.5, "horizon": 0.55, "focal_x": 0.5, "warmth": 0}',
        ] if x)

    def _paint(self, job):
        """Plan, paint, show it to a stranger, learn. All-or-nothing like a tick."""
        st = copy.deepcopy(self.state)
        v = self.view(st)
        pid = st["next_painting_id"]
        skill = skill_level(st["skills"]["paint"])
        index = self.paint_index()

        raw = self.think(self.system_prompt(st), self.plan_prompt(st, v, job, skill, index), 900)
        place = match_place(raw.get("place")) or (match_place(job["subject"]) if job["subject"] else None) or st["place"]
        tod = "night" if not v["is_day"] else {"dawn": "dawn", "evening": "dusk"}.get(v["tod"], "day")
        plan = painter.normalize_plan(raw, place, tod, self._sky_to_weather(v["sky"]))
        png = painter.make_painting(plan, skill, pid * 7919 + st["tick"], self.cfg["paint_width"], self.cfg["paint_height"])

        # the stranger is told nothing - that's what keeps the feedback honest
        seen_raw = self.think(self.CRITIC_SYSTEM, self.CRITIC_PROMPT, 700, image_b64=base64.b64encode(png).decode())
        seen = {k: clean(seen_raw.get(k), 300) for k in ("sees", "subject_guess", "time_guess", "weather_guess", "mood_guess", "weakest_part")}
        score, hits = painter.recognition(plan, seen)
        got = [k for k, ok in hits.items() if ok]
        missed = [k for k, ok in hits.items() if not ok]

        try:
            les = self.think(self.system_prompt(st),
                             f"You just painted \"{plan['title']}\". You meant: {plan['intent'] or '(no plan written)'} "
                             f"({plan['place']}, {plan['time']}, {plan['weather']}, mood {plan['mood']}, focal {plan['focal']}).\n"
                             f"Your settings: contrast {plan['contrast']:.2f}, detail {plan['detail']:.2f}, sharpness {plan['sharpness']:.2f}, "
                             f"brush {plan['brush']:.2f}, horizon {plan['horizon']:.2f}, warmth {plan['warmth']:.2f}, palette {plan['palette']}.\n"
                             f"A stranger who knew nothing about it said: \"{seen['sees']}\" They guessed: place \"{seen['subject_guess']}\", "
                             f"time \"{seen['time_guess']}\", weather \"{seen['weather_guess']}\", mood \"{seen['mood_guess']}\". "
                             f"Hardest to make out: \"{seen['weakest_part']}\".\n"
                             f"They got right: {', '.join(got) or 'nothing'}. They missed: {', '.join(missed) or 'nothing'}.\n"
                             "Write: diary (1-2 sentences, how you feel about how it came out, your voice), lesson (ONE concrete "
                             "thing to do differently next time, naming a setting and which way to move it, e.g. 'sharpness up for "
                             "mountains so they don't read as lumps'), feeling (-2 to 2). "
                             'Reply JSON: {"diary": "...", "lesson": "...", "feeling": 0}', 700)
        except BrainError:
            les = {}
        diary = clean(les.get("diary"), 400) or f"Painted \"{plan['title']}\". A stranger thought it was {seen['subject_guess'] or 'something'}."
        lesson = clean(les.get("lesson"), 240)
        try:
            feeling = clamp(int(round(float(les.get("feeling", 0)))), -2, 2)
        except (TypeError, ValueError):
            feeling = 0

        # commit: image, then index, then memory + state. Re-running a half-finished job just overwrites #pid.
        pdir = self.dir / "paintings"
        pdir.mkdir(exist_ok=True)
        fname = f"{pid:04d}.png"
        tmp = pdir / (fname + ".tmp")
        with open(tmp, "wb") as f:
            f.write(png)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, pdir / fname)
        entry = {"id": pid, "file": fname, "t": v["now"].isoformat(timespec="seconds"), "title": plan["title"],
                 "by": job["by"], "request": job["subject"], "kind": job["kind"], "skill": skill, "plan": plan,
                 "seen": seen, "hits": hits, "hits_n": len(got), "checks": len(hits), "score": round(score, 2),
                 "lesson": lesson, "diary": diary, "feeling": feeling}
        index = [e for e in index if e["id"] != pid] + [entry]
        atomic_write(pdir / "index.json", json.dumps(index, ensure_ascii=False, indent=1))

        st["next_painting_id"] = pid + 1
        before = skill_level(st["skills"]["paint"])
        st["skills"]["paint"] = round(st["skills"]["paint"] + 1 + 3 * score, 2)
        leveled = skill_level(st["skills"]["paint"]) > before
        if lesson:
            st["art_notes"] = (st["art_notes"] + [lesson])[-40:]
        today = self._today()
        st["paint_days"] = {d: n for d, n in st["paint_days"].items() if d == today}
        st["paint_days"][today] = st["paint_days"].get(today, 0) + 1
        st["paint_queue"] = [j for j in st["paint_queue"] if not (j["t"] == job["t"] and j["kind"] == job["kind"])]
        if job["kind"] == "daily":
            st["last_daily_paint"] = today
        st["prefs"]["paint"] = st["prefs"].get("paint", 0.0) * 0.97 + feeling
        st["mood"] = clamp(st["mood"] * 0.9 + feeling, -10, 10)
        for_who = f" for {job['by']}" if job["by"] else ""
        st["outbox"].append({"text": f"{stamp(v['now'])} [{st['place']}, {v['sky']}, energy {st['energy']:.0f}] "
                                     f"painted \"{no_md(plan['title'])}\"{for_who} -> {no_md(diary)} ({feel(feeling)})\n"
                                     f"-# a stranger saw: {no_md(seen['sees']) or '...'}",
                             "t": self.clock.time(), "file": str(pdir / fname), "reply_to": job["msg_id"]})
        special = pid == 1 or score >= 0.8 or abs(feeling) == 2 or leveled
        self._commit(st, [self._mem(st, entry["t"], "paint",
                                    f"{diary} [painting #{pid}: {plan['title']}; a stranger got {len(got)}/{len(hits)}]",
                                    feeling, special)])
        try:
            self.write_gallery(index)
        except OSError as e:
            log(f"gallery write failed: {e}")
        return f"painted #{pid} \"{plan['title']}\" - stranger got {len(got)}/{len(hits)} ({', '.join(got) or 'nothing'})"

    def write_gallery(self, index):
        esc = html.escape
        name = esc(self.state["name"] or "The jay")
        recent = index[-10:]
        avg = sum(e["score"] for e in recent) / len(recent) if recent else 0
        cards = []
        for e in reversed(index):
            checks = " ".join(f'<span class="{"y" if ok else "n"}">{esc(k)}</span>' for k, ok in e["hits"].items())
            who = ""
            if e["by"]:
                who = f" &middot; for {esc(e['by'])}" + (f": &ldquo;{esc(e['request'])}&rdquo;" if e["request"] else "")
            lesson = f"<p><b>Lesson:</b> {esc(e['lesson'])}</p>" if e["lesson"] else ""
            cards.append(
                f'<article><img src="paintings/{esc(e["file"])}" alt="{esc(e["title"])}" loading="lazy">'
                f'<h2>#{e["id"]} {esc(e["title"])}</h2>'
                f'<p class="meta">{esc(e["t"][:16].replace("T", " "))} &middot; skill {e["skill"]}{who}</p>'
                f'<p><b>Meant:</b> {esc(e["plan"].get("intent") or "-")}</p>'
                f'<p><b>A stranger saw:</b> {esc(e["seen"].get("sees") or "-")}</p>'
                f'<p class="checks">{checks}</p><p><b>{name}:</b> {esc(e["diary"])}</p>{lesson}</article>')
        style = """
:root{--bg:#f6f3ee;--card:#fff;--ink:#222;--dim:#6b6b6b;--y:#2f7d4a;--n:#b0413e;--line:#e4dfd6}
@media (prefers-color-scheme:dark){:root{--bg:#17181b;--card:#222428;--ink:#e8e6e3;--dim:#9a9a9a;--y:#5fbf7f;--n:#e07a76;--line:#33363b}}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,sans-serif}
header{padding:24px 16px 8px;max-width:1200px;margin:auto} h1{margin:0 0 4px;font-size:26px} header p{margin:0;color:var(--dim)}
main{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px;padding:16px;max-width:1200px;margin:auto}
article{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
article img{width:100%;display:block;aspect-ratio:4/3;object-fit:cover} article h2{font-size:17px;margin:10px 12px 0}
article p{margin:6px 12px} article p:last-child{margin-bottom:12px} .meta{color:var(--dim);font-size:13px}
.checks span{font-size:12px;margin-right:6px;padding:1px 6px;border-radius:9px;border:1px solid}
.y{color:var(--y)} .n{color:var(--n);text-decoration:line-through}
"""
        page = (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                f"<title>{name}'s Paintings</title><style>{style}</style></head><body><header><h1>{name}'s Paintings</h1>"
                f"<p>{len(index)} paintings &middot; painting skill {skill_level(self.state['skills']['paint'])}/10 &middot; "
                f"strangers recognize {avg * 100:.0f}% of what he means (last {len(recent)})</p></header>"
                f"<main>{''.join(cards)}</main></body></html>")
        atomic_write(self.dir / "gallery.html", page)

    # ---------- Discord: listening and answering

    def author_name(self, a):
        u = a.get("username", "someone")
        return self.names.get(u) or a.get("global_name") or u

    def is_bolt(self, a):
        if self.cfg["bolt_user_id"]:
            return str(a.get("id")) == str(self.cfg["bolt_user_id"])
        hint = self.cfg["bolt_name_hint"].lower()
        return bool(a.get("bot")) and hint in (a.get("username", "") + " " + (a.get("global_name") or "")).lower()

    def note_bolt(self, text):
        b = self.state["bolt"]
        now = self.clock.time()
        b["last_t"] = now
        b["feed"] = (b["feed"] + [{"t": now, "text": clean(text, 500)}])[-30:]
        place = find_place_mention(text)
        if place:
            b["place"], b["place_t"] = place, now

    def addressed_to_me(self, m):
        name = (self.state["name"] or "jay").lower()
        if re.search(r"\b" + re.escape(name) + r"\b", m.get("content", "").lower()):
            return True
        if any(str(u.get("id")) == str(self.me_id) for u in m.get("mentions", [])):
            return True
        ref = m.get("referenced_message") or {}
        return str((ref.get("author") or {}).get("id")) == str(self.me_id)

    def poll_discord(self):
        if not self.discord:
            return
        if self.me_id is None:
            self.me_id = str(self.discord.me()["id"])
        if not self.state["gateway_ok"] and hasattr(self.discord, "identify_once"):
            try:
                self.state["gateway_ok"] = bool(self.discord.identify_once())
                log("identified on the Discord gateway" if self.state["gateway_ok"] else "gateway identify got no READY")
            except Exception as e:
                log(f"gateway identify failed (posting may not work until it succeeds): {e}")
                self.state["gateway_ok"] = True   # don't hammer it; REST posting usually works anyway
        st = self.state
        first = st["discord_cursor"] is None
        msgs = self.discord.fetch(after=st["discord_cursor"], limit=50 if not first else 20)
        if first and not msgs:
            st["discord_cursor"] = "0"     # empty channel: we're caught up, so answer from now on
        for m in msgs:
            st["discord_cursor"] = m["id"]
            a = m.get("author") or {}
            if str(a.get("id")) == self.me_id:
                self.channel_log.append(("me", m.get("content", "")))
                continue
            bolt = self.is_bolt(a)
            if a.get("bot") and not bolt:
                continue
            content = m.get("content", "") or ""
            who = "Bolt" if bolt else self.author_name(a)
            self.channel_log = (self.channel_log + [("bolt" if bolt else who, content)])[-12:]
            if not a.get("bot"):
                st["bolt_streak"], st["bolt_rest_until"] = 0, 0.0     # a human spoke: Bolt's break ends too
            if bolt:
                self.note_bolt(content)
            if first:
                continue       # catching up on history: learn from it, don't answer it
            named = self.named_command(content)
            if bolt and content.startswith("!"):
                continue       # Bolt doesn't get to run our commands
            if content.lower().startswith("!jay"):
                self.command(m, who, content)
            elif named:
                self.command(m, who, named)
            elif not content.startswith("!") and self.addressed_to_me(m):
                self.reply(m, who, content, bolt)
        self.save()

    def bot_chain_too_long(self):
        """True once we and Bolt have gone back and forth twice with no human in between.
        Bolt's ordinary diary posts don't count; only his posts that answer us do."""
        tag = f"**{self.state['name']}:**".lower()
        n = 0
        for who, content in reversed(self.channel_log):
            if who == "me" or (who == "bolt" and tag in content.lower()):
                n += 1
            elif who != "bolt":
                break
        return n >= 4

    def reply(self, m, who, content, bolt):
        st = self.state
        now = self.clock.time()
        if bolt:
            # Bolt's reply posts quote whoever spoke ("**Spike:** ..."), and that's the only Bolt post worth
            # answering. His other posts (diary, "*Spike hid a lure...*" notices) only mention us in passing.
            if f"**{st['name']}:**".lower() not in content.lower():
                return
            if self.bot_chain_too_long() or not self.can_message_bolt(st):
                return
        else:
            st["replies"] = [t for t in st["replies"] if now - t < 3600]
            if len(st["replies"]) >= self.cfg["max_replies_per_hour"]:
                return
        person = st["people"].setdefault(who, {"facts": [], "talks": 0})
        recent = "\n".join(f"{w}: {clean(c, 200)}" for w, c in self.channel_log[-8:])
        mine = "\n".join(f"- {x['text']}" for x in self.memories[-4:])
        where = "asleep in the fir (they woke you up)" if st["asleep"] else f"at {PLACES[st['place']]['name']}"
        try:
            obj = self.think(self.system_prompt(st),
                             f"You're {where}. Energy {st['energy']:.0f}/100, mood {mood_word(st['mood'])}.\n"
                             f"WHAT YOU'VE BEEN DOING:\n{mine}\n"
                             f"WHAT YOU KNOW ABOUT {who.upper()}: {'; '.join(person['facts']) or 'nothing yet'}\n"
                             + (f"WHAT YOU THINK OF BOLT: {st['about_bolt']}\n" if bolt else "")
                             + f"RECENT CHAT:\n{recent}\n\n{who} just said to you: \"{clean(content, 500)}\"\n"
                             "Answer as yourself, 1-3 short sentences. Only use 'remember' for a fact about "
                             f"{who} that THEY said about themselves (otherwise leave it empty). "
                             'Reply JSON: {"reply": "...", "remember": ""}', 800)
        except (BrainError, BudgetExceeded):
            return
        text = no_command(clean(obj.get("reply"), 600))
        if not text:
            return
        fact = clean(obj.get("remember"), 160)
        if fact and fact not in person["facts"]:
            person["facts"] = (person["facts"] + [fact])[-20:]
        person["talks"] += 1
        if bolt:
            self.sent_to_bolt(st, talk=True)
        else:
            st["replies"].append(now)
        said = no_md(content)
        if bolt:   # quote just what Bolt said, not his whole post
            lines = re.findall(r"^\*\*Bolt:\*\*\s*(.+)$", content, re.M)
            said = no_md(lines[-1]) if lines else said
        # Bolt's conversation layout. It goes out as a Discord reply, which is also how Bolt knows it's for him.
        st["outbox"].append({"text": f"{stamp(self.clock.now())}\n**{no_md(who)}:** {clean(said, 300)}\n"
                                     f"**{st['name']}:** {no_md(text)}", "t": now, "reply_to": m["id"]})
        self.remember(self._mem(st, self.clock.now().isoformat(timespec="seconds"), "talk",
                                f"{who} said \"{clean(content, 200)}\" and I said \"{text}\"", 1, bolt))
        self.save()

    NAMED_COMMANDS = {"give": "give", "leave": "leave", "hide": "leave", "paint": "paint", "status": "status",
                      "help": "help", "stop": "pause", "start": "resume"}

    def named_command(self, content):
        """Bolt's convention for a shared channel: '!give spike a feather', '!stop spike'. Returns it as a
        '!jay ...' command, or None if it isn't a command naming us (an unnamed '!give' is left to Bolt)."""
        parts = content.strip().split(None, 2)
        if len(parts) < 2 or not parts[0].startswith("!") or not self.state["name"]:
            return None
        if parts[1].strip("@,:").lower() != self.state["name"].lower():
            return None
        cmd = self.NAMED_COMMANDS.get(parts[0][1:].lower())
        return f"!jay {cmd} {parts[2] if len(parts) > 2 else ''}".strip() if cmd else None

    def command(self, m, who, content):
        st = self.state
        parts = content.split(None, 2)
        cmd = parts[1].lower() if len(parts) > 1 else "help"
        cmd = {"stop": "pause", "start": "resume", "hide": "leave"}.get(cmd, cmd)
        arg = parts[2] if len(parts) > 2 else ""
        owner = str((m.get("author") or {}).get("id")) == str(self.cfg["owner_discord_id"]) and self.cfg["owner_discord_id"]
        name = st["name"] or "the jay"
        if cmd == "give" and clean(arg, 60):
            thing = clean(arg, 60)
            self.inv_add(st, f"{thing} from {who}", "gift", from_=who)
            st["events"].append(f"{who} just gave you {thing}.")
            self.remember(self._mem(st, self.clock.now().isoformat(timespec="seconds"), "gift",
                                    f"{who} gave me {thing}.", 2, True))
            st["outbox"].append({"text": f"*{name} grabs the {thing} and inspects it suspiciously*", "t": self.clock.time(), "reply_to": m["id"]})
        elif cmd == "leave":
            bits = arg.split(None, 1)
            place = match_place(bits[0]) if bits else None
            if len(bits) == 2 and place and place != "fir":
                st["hidden"].append({"place": place, "thing": clean(bits[1], 60), "from": who})
                st["outbox"].append({"text": f"(hidden at {PLACES[place]['name']}. {name} will find it if he goes there)",
                                     "t": self.clock.time(), "reply_to": m["id"]})
            else:
                st["outbox"].append({"text": "usage: !jay leave <place> <thing>  places: " + ", ".join(p for p in PLACES if p != "fir"),
                                     "t": self.clock.time(), "reply_to": m["id"]})
        elif cmd == "paint":
            queued = len(st["paint_queue"])
            if self.paintings_today(st) + queued >= self.cfg["max_paintings_per_day"]:
                msg = f"({name} is out of paint for today. Try tomorrow.)"
            elif sum(1 for j in st["paint_queue"] if j["kind"] == "request") >= 3:
                msg = f"({name} already has a pile of requests. Give him a minute.)"
            else:
                self.queue_painting(st, "request", who, arg, m["id"])
                msg = (f"({name} is asleep. He'll paint it when he wakes up.)" if st["asleep"]
                       else f"*{name} squints at a blank canvas*")
            st["outbox"].append({"text": msg, "t": self.clock.time(), "reply_to": m["id"]})
        elif cmd == "status":
            st["outbox"].append({"text": self.status_text(), "t": self.clock.time(), "reply_to": m["id"]})
        elif cmd in ("pause", "resume") and owner:
            st["paused"] = cmd == "pause"
            st["outbox"].append({"text": f"({name} is {'paused' if st['paused'] else 'back'})", "t": self.clock.time()})
        else:
            st["outbox"].append({"text": f"!jay give <thing> | !jay leave <place> <thing> | !jay paint <anything> | !jay status"
                                 f"  (or name him: !give {name.lower()} <thing>, !paint {name.lower()} <anything>)"
                                 + (" | !jay pause | !jay resume" if owner else ""), "t": self.clock.time(), "reply_to": m["id"]})
        self.save()

    def status_text(self):
        st = self.state
        sk = ", ".join(f"{s} {skill_level(x)}" for s, x in st["skills"].items())
        return (f"{st['name'] or 'unnamed jay'} | {'asleep' if st['asleep'] else 'awake'} at {PLACES[st['place']]['name']} | "
                f"energy {st['energy']:.0f} | mood {mood_word(st['mood'])} | tick {st['tick']} | {sk} | "
                f"{len(st['caches'])} caches | spent today ${self.spent_today():.3f} of ${self.cfg['daily_budget_usd']:.2f}")

    def flush_outbox(self):
        st = self.state
        if not st["outbox"]:
            return
        if not self.discord:
            for o in st["outbox"]:
                log(f"(discord off) would post: {o['text']}" + (f"  [{o['file']}]" if o.get("file") else ""))
            st["outbox"] = []
            self.save()
            return
        while st["outbox"]:
            o = st["outbox"][0]
            if self.clock.time() - o["t"] > 3600:
                st["outbox"].pop(0)
                continue
            try:
                self.discord.send(o["text"], o.get("reply_to"), o.get("file"))
            except Exception as e:
                log(f"discord send failed, will retry: {e}")
                break
            st["outbox"].pop(0)
            self.save()
        if st["name"] and not st["nick_set"]:
            try:
                self.discord.set_nick(st["name"])
            except Exception as e:
                log(f"couldn't set nickname (needs Change Nickname permission): {e}")
            st["nick_set"] = True
            self.save()

    # ---------- the loop

    def safe_tick(self):
        try:
            what = self.tick()
            log(f"{self.state['name'] or 'jay'} @ {PLACES[self.state['place']]['name']}: {what}")
            return True
        except BudgetExceeded:
            if self.budget_warned != self._today():
                log(f"daily budget of ${self.cfg['daily_budget_usd']:.2f} reached; resting until tomorrow")
                self.budget_warned = self._today()
            return True
        except Exception:
            log("tick failed:\n" + traceback.format_exc())
            return False

    def run(self):
        next_tick = next_poll = 0.0
        fails = 0
        while True:
            now = self.clock.time()
            if self.discord and now >= next_poll:
                try:
                    self.poll_discord()
                except Exception as e:
                    log(f"discord poll failed: {e}")
                next_poll = now + self.cfg["discord_poll_seconds"]
            try:
                self.flush_outbox()
            except Exception as e:
                log(f"outbox failed: {e}")
            if self.state["paint_queue"]:
                what = self.paint_next()
                if what:
                    log(what)
            if now >= next_tick:
                ok = self.safe_tick()
                fails = 0 if ok else fails + 1
                next_tick = now + (self.cfg["tick_seconds"] if ok else min(60 * 2 ** fails, 1800))
            self.clock.sleep(1)


def mood_word(m):
    return ("giddy" if m >= 6 else "cocky and bright" if m >= 3 else "pretty good" if m >= 1 else
            "okay" if m > -1 else "grumpy" if m > -3 else "sulky" if m > -6 else "miserable")


def main():
    global LOG_PATH
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    cfg = load_config()
    data = BASE / "data"
    data.mkdir(exist_ok=True)
    LOG_PATH = data / "jay.log"
    lock = InstanceLock(data / "jay.lock")
    if not lock.acquire():
        print("Another jay is already running (data/jay.lock is held).")
        sys.exit(1)
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        print("Set OPENAI_API_KEY first (see README).")
        sys.exit(1)
    token = os.environ.get("JAY_DISCORD_TOKEN")
    discord = Discord(token, cfg["discord_channel_id"]) if token and cfg["discord_channel_id"] else None
    if not discord:
        log("Discord is off (no JAY_DISCORD_TOKEN or discord_channel_id). He'll live quietly; see data/diary.md.")
    names = load_json(BASE / "names.json", {})
    jay = Jay(cfg, data, OpenAIBrain(cfg, key), discord, Weather(cfg["latitude"], cfg["longitude"]), names=names)
    log(f"waking up {jay.state['name'] or 'a nameless jay'} (tick {jay.state['tick']}, model {cfg['model']}, "
        f"budget ${cfg['daily_budget_usd']:.2f}/day)")
    if "--paint" in sys.argv:         # paint one picture right now: python jay.py --paint "the lake in a storm"
        i = sys.argv.index("--paint")
        subject = sys.argv[i + 1] if len(sys.argv) > i + 1 else ""
        jay.queue_painting(jay.state, "request", None, subject)
        jay.state["paint_queue"][-1]["force"] = True
        log(jay.paint_next() or "he didn't paint (see the log above)")
        jay.flush_outbox()
        return
    if "--once" in sys.argv:          # one real tick, then quit: for checking the key, model and Discord
        if discord:
            jay.poll_discord()
        jay.safe_tick()
        jay.paint_next()
        jay.flush_outbox()
        log(jay.status_text())
        return
    try:
        jay.run()
    except KeyboardInterrupt:
        log("stopped")


if __name__ == "__main__":
    main()
