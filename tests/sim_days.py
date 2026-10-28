#!/usr/bin/env python3
"""
Simulate days of the jay's life in seconds with a chaotic fake brain, fake Discord,
fake weather and a fake clock. Injects junk replies, Chinese replies, network errors
and power cuts mid-save, restarts him from disk, and checks invariants every step.

    python tests/sim_days.py [days] [seed]

Exits non-zero on the first broken invariant.
"""

import json
import random
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jay as J  # noqa: E402


class PowerCut(BaseException):
    """BaseException so no `except Exception` in the code can swallow it - a real power cut can't be caught either."""


class FakeClock:
    def __init__(self, start):
        self.dt = start

    def now(self):
        return self.dt

    def time(self):
        return self.dt.timestamp()

    def sleep(self, s):
        self.dt += timedelta(seconds=s)


class FakeWeather:
    def __init__(self, clock, rng):
        self.clock, self.rng = clock, rng

    def get(self):
        if self.rng.random() < 0.05:
            return None
        h = self.clock.now().hour
        return {"temp_f": self.rng.uniform(20, 75), "wind_mph": self.rng.uniform(0, 35),
                "code": self.rng.choice(list(J.WEATHER_CODES)), "is_day": 7 <= h < 18}


class ChaosBrain:
    def __init__(self, rng):
        self.rng = rng
        self.calls = 0
        self.leaks = []         # critic calls that were told something about the painting

    def ask(self, system, user, max_tokens=1200, image_b64=None):
        self.calls += 1
        if image_b64 is not None and (user != J.Jay.CRITIC_PROMPT or system != J.Jay.CRITIC_SYSTEM):
            self.leaks.append(user[:80])
        r = self.rng.random()
        if r < 0.05:
            raise J.BrainError("fake outage")
        cost = 0.0004
        if r < 0.12:
            return None, cost
        if r < 0.15:
            return {"diary": "我今天很开心", "action": "去", "reply": "你好"}, cost
        if r < 0.20:
            return {"action": 5, "target": ["x"], "feeling": "lots", "diary": "x" * 5000, "name": "!!"}, cost
        R = self.rng
        if '"name"' in user:
            return {"name": R.choice(["Skreech", "Bolt", "Jay", "Cobalt", "a b c", "Mischief"]), "why": "sounds right"}, cost
        if '"who_i_am"' in user:
            return {"who_i_am": "I'm a jay who hides acorns and screams at hawks. " * R.randint(1, 3),
                    "how_i_talk": "Loud and short.", "about_bolt": "Bolt is a crow who thinks too much."}, cost
        if '"reply"' in user:
            return {"reply": R.choice(["Hah.", "Mine now.", "", "Bolt you're slow."]),
                    "remember": R.choice(["", "likes trains", "has a dog"])}, cost
        if '"intent"' in user:
            return {"title": R.choice(["Lake Thing", "", "x" * 300, "Bolt Sulking"]), "intent": "a quiet lake",
                    "place": R.choice(list(J.PLACES) + ["mars", "", None]), "time": R.choice(["dusk", "noon", 3]),
                    "weather": R.choice(["fog", "snow", "lava"]), "focal": R.choice(["mountain", "bird", "dragon"]),
                    "bird": R.choice(["bolt", "me", "eagle"]), "mood": R.choice(["calm", "wild", "angsty"]),
                    "palette": R.choice([["#ff0000", "#00f", "nope"], "red", [], None, ["#123456"] * 9]),
                    "contrast": R.choice([0.2, 1.7, -3, "high", None]), "detail": R.random(), "sharpness": R.random(),
                    "brush": R.random(), "horizon": R.choice([0.1, 0.5, 0.9, "low"]), "focal_x": R.random(),
                    "warmth": R.choice([-1, 0, 5])}, cost
        if '"subject_guess"' in user:
            return {"sees": R.choice(["A lake at dusk with a mountain.", "Colorful noise.", "", "A barn at night, gloomy."]),
                    "subject_guess": R.choice(["lake", "barn", "train tracks", "abstract"]), "time_guess": R.choice(["dusk", "night", "day"]),
                    "weather_guess": R.choice(["clear", "fog", "storm"]), "mood_guess": R.choice(["calm", "gloomy", "wild"]),
                    "weakest_part": "the middle"}, cost
        if '"lesson"' in user:
            return {"diary": R.choice(["Not bad.", "It looks like soup.", ""]), "lesson": R.choice(["contrast up", "", "sharpness up for peaks"]),
                    "feeling": R.choice([-2, 0, 2, "meh"])}, cost
        if '"diary"' in user:
            return {"diary": R.choice(["Got it.", "Ugh, the cook again.", "Best acorn of my life.", ""]),
                    "feeling": R.choice([-2, -1, 0, 1, 2, "1", 2.7, None])}, cost
        acts = ["go", "forage", "raid", "snatch", "mimic", "scold", "watch", "think", "nap", "eat", "cache",
                "recover", "treasure", "reminisce", "talk_to_bolt", "give_bolt", "leave_for_bolt", "fly", "dance"]
        targets = list(J.PLACES) + ["the summit", "Lake", "black oak acorn", "bottle cap", "train horn",
                                    "hey Bolt, race you to the summit", "", "mars", "shiny marble"]
        return {"action": R.choice(acts), "target": R.choice(targets),
                "item": R.choice(["bottle cap", "black oak acorn", "mirror shard", "french fry", "",
                                  "shiny marble", "candy wrapper from Elliott"]),
                "why": "because"}, cost


class FakeDiscord:
    def __init__(self, clock, rng):
        self.clock, self.rng = clock, rng
        self.next_id = 1000
        self.files = 0
        self.bolt_ids = set()   # ids of messages Bolt wrote, so replies to him can be counted
        self.jay_name = lambda: "Skreech"
        self.sent = []          # (time, text)

    def me(self):
        return {"id": "999"}

    def fetch(self, after=None, limit=50):
        out = []
        for _ in range(self.rng.choice([0, 0, 0, 1, 2])):
            self.next_id += 1
            kind = self.rng.random()
            if kind < 0.4:
                author = {"id": "42", "username": "boltcrow", "bot": True}
                self.bolt_ids.add(str(self.next_id))
                content = self.rng.choice(["Flew up to the summit, the wind is wild.",
                                           "Wrote a song called \"Cold Iron\" at the rail yard.",
                                           "Skreech, are you the jay screaming at the junkyard?",
                                           "Back at my nest.",
                                           f"**{self.jay_name()}:** Bolt! race you\n**Bolt:** no way, I'm fishing"])
            elif kind < 0.5:
                author = {"id": "7", "username": "someotherbot", "bot": True}
                content = "Skreech Skreech Skreech"
            else:
                author = {"id": "5", "username": "ellwood2150"}
                content = self.rng.choice(["!jay give shiny marble", "!jay leave lake candy wrapper", "!jay status",
                                           "!jay pause", "hey Skreech what's up", "!give Bolt a rock", "hi jay",
                                           "!jay leave nowhere thing", "!jay",
                                           "!jay paint the lake at night", "!jay paint", "!jay paint Bolt looking smug"])
            out.append({"id": str(self.next_id), "author": author, "content": content, "mentions": []})
        return out

    def send(self, text, reply_to=None, file_path=None):
        if self.rng.random() < 0.05:
            raise OSError("fake discord down")
        if file_path:
            assert Path(file_path).exists(), f"posting a painting that isn't on disk: {file_path}"
            self.files += 1
        to_bolt = text.startswith(("Bolt! ", "!give ", "!leave ")) or str(reply_to) in self.bolt_ids
        self.sent.append((self.clock.time(), text, to_bolt))

    def set_nick(self, nick):
        pass


def gifts(st):
    return sum(it["count"] for it in st["inv"].values() if it["kind"] == "gift")


def check(j, prev, cfg):
    st = j.state
    assert 0 <= st["energy"] <= 100, st["energy"]
    assert -10 <= st["mood"] <= 10, st["mood"]
    assert st["place"] in J.PLACES
    for n, it in st["inv"].items():
        assert isinstance(it["count"], int) and it["count"] >= 1, (n, it)
    for s in st["shelf"]:
        assert s in st["inv"], s
    assert len(st["shelf"]) <= 10
    for c in st["caches"]:
        assert c["place"] in J.PLACES and c["food"] in J.ALL_FOODS, c
    assert st["tick"] >= prev["tick"], (st["tick"], prev["tick"])
    assert gifts(st) >= prev["gifts"], (gifts(st), prev["gifts"])
    ticks = [m["tick"] for m in j.memories]
    assert all(t <= st["tick"] for t in ticks)
    assert all(a <= b for a, b in zip(ticks, ticks[1:])), "memory out of order"
    assert j.spent_today() <= cfg["daily_budget_usd"] + 0.0004 * 2 + 1e-9, j.spent_today()
    if st["name"]:
        assert st["name"].lower() not in ("bolt", "jay"), st["name"]
    for s in st["sounds"].values():
        assert 0 <= s <= 10
    for _, text, _ in j.discord.sent:
        assert len(text) <= 1900


def check_paintings(j, cfg):
    idx = J.load_json(j.dir / "paintings" / "index.json", [])
    ids = [e["id"] for e in idx]
    assert len(ids) == len(set(ids)), "duplicate painting ids"
    assert not ids or max(ids) <= j.state["next_painting_id"], (max(ids), j.state["next_painting_id"])
    per_day = {}
    for e in idx:
        data = (j.dir / "paintings" / e["file"]).read_bytes()
        assert J.painter.png_ok(data), f"broken png {e['file']}"
        assert 0 <= e["score"] <= 1 and e["checks"] in (4, 5)
        per_day[e["t"][:10]] = per_day.get(e["t"][:10], 0) + 1
    for d, n in per_day.items():
        assert n <= cfg["max_paintings_per_day"] + 1, f"{n} paintings on {d}"
    assert len(j.state["paint_queue"]) <= cfg["max_paintings_per_day"] + 1
    assert 0 <= J.skill_level(j.state["skills"]["paint"]) <= 10
    return len(idx)


def bolt_rate_ok(sent, cfg):
    """Talking to Bolt, !give, !leave and replies to Bolt all share one hourly limit.
    A resend after a power cut (at-least-once delivery) can add one duplicate."""
    bolt = [t for t, _, to_bolt in sent if to_bolt]
    for i, t in enumerate(bolt):
        window = [x for x in bolt[i:] if x - t < 3600]
        if len(window) > cfg["max_bolt_messages_per_hour"] + 1:
            return False
    return True


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    rng = random.Random(seed)
    tmp = Path(tempfile.mkdtemp(prefix="jay_sim_"))
    cfg = J.load_config(tmp / "none.json")
    cfg.update(daily_budget_usd=0.12, bolt_accepts_bots=True, owner_discord_id="5", post_diary="all",
               paint_width=120, paint_height=90)
    clock = FakeClock(datetime(2026, 10, 28, 6, 0))
    discord = FakeDiscord(clock, rng)
    brain = ChaosBrain(rng)
    weather = FakeWeather(clock, rng)
    J.log = lambda msg: None

    real_write, real_append = J.atomic_write, J.append_line

    def flaky_write(path, text):
        if rng.random() < 0.01:
            tmpf = Path(path).with_name(Path(path).name + ".tmp")
            tmpf.write_text(text[: len(text) // 2], encoding="utf-8")
            raise PowerCut()
        real_write(path, text)

    def flaky_append(path, text):
        if rng.random() < 0.01:
            with open(path, "a", encoding="utf-8") as f:
                f.write(text[: len(text) // 2])     # torn line, no newline
            raise PowerCut()
        real_append(path, text)

    J.atomic_write, J.append_line = flaky_write, flaky_append

    def boot():
        while True:     # the power can go out again while he's repairing files on startup
            try:
                return J.Jay(cfg, tmp, brain, discord, weather, clock, random.Random(rng.random()),
                             names={"ellwood2150": "Elliott"})
            except PowerCut:
                continue

    j = boot()
    holder = {"j": j}
    discord.jay_name = lambda: holder["j"].state["name"] or "jay"
    prev = {"tick": 0, "gifts": 0}
    steps = days * 24 * 60 * 60 // cfg["tick_seconds"]
    restarts = crashes = 0
    try:
        for step in range(steps):
            try:
                j.poll_discord()
                j.flush_outbox()
                j.tick()
                j.paint_next()
                if j.state["paused"] and rng.random() < 0.2:
                    j.state["paused"] = False
            except PowerCut:
                restarts += 1
                j = boot()                 # power came back: fresh process, state from disk
                holder["j"] = j
            except J.BudgetExceeded:
                pass
            except J.BrainError:
                crashes += 1
            check(j, prev, cfg)
            if step % 24 == 0:
                check_paintings(j, cfg)
            prev = {"tick": j.state["tick"], "gifts": gifts(j.state)}
            clock.sleep(cfg["tick_seconds"])
        assert bolt_rate_ok(discord.sent, cfg), "too many messages to Bolt in an hour"
        assert not brain.leaks, f"the critic was told about the painting: {brain.leaks[:2]}"
        paintings = check_paintings(j, cfg)
        assert paintings >= days - 1, f"only {paintings} paintings in {days} days"
        # A clean reload must reproduce the same state.
        J.atomic_write, J.append_line = real_write, real_append
        j.save()
        again = boot()
        assert json.dumps(again.state, sort_keys=True) == json.dumps(j.state, sort_keys=True), "reload differs"
    except AssertionError as e:
        print(f"FAILED at step {step} (sim time {clock.now()}): {e}")
        print(f"data left in {tmp}")
        raise SystemExit(1)

    st = j.state
    print(f"OK: {days} days, {steps} steps, {restarts} power cuts, {brain.calls} brain calls, "
          f"{len(discord.sent)} posts, {paintings} paintings ({discord.files} posted)")
    print(f"   name={st['name']} tick={st['tick']} energy={st['energy']:.0f} mood={J.mood_word(st['mood'])} "
          f"items={len(st['inv'])} gifts={gifts(st)} caches={len(st['caches'])} sounds={list(st['sounds'])}")
    print(f"   skills={ {k: J.skill_level(v) for k, v in st['skills'].items()} } memories={len(j.memories)} "
          f"spent_today=${j.spent_today():.3f}")
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
