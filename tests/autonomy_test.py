#!/usr/bin/env python3
"""
How the jay decides for himself: needs that build up, a short menu drawn from them, boredom, the shape of a day,
daily goals, capped preferences, a smarter model for deciding and talking, no parroting, and knowing where Bolt is.
The big one: a stubborn brain that always says "snatch" still lives a varied day.

    python tests/autonomy_test.py
"""

import collections
import random
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jay as J  # noqa: E402

J.log = lambda msg: None
PROBLEMS = []


def check(ok, what):
    print(("  ok   " if ok else "  FAIL ") + what)
    if not ok:
        PROBLEMS.append(what)


class Clock:
    def __init__(self, dt):
        self.dt = dt

    def now(self):
        return self.dt

    def time(self):
        return self.dt.timestamp()

    def sleep(self, s):
        self.dt += timedelta(seconds=s)


class Brain:
    """Always wants the same thing (gpt-5-nano at its worst), and records which model each call asked for."""

    def __init__(self):
        self.act = {"action": "snatch", "target": "", "item": "", "why": "shiny"}
        self.goals = []
        self.replies = ["Hah."]
        self.calls = []

    def ask(self, system, user, max_tokens=1200, image_b64=None, model=None):
        self.calls.append((model, user))
        if '"goals"' in user:
            return {"goals": self.goals}, 0.0
        if '"reply"' in user:
            return {"reply": self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]}, 0.0
        if '"diary"' in user:
            return {"diary": "Did a thing.", "feeling": 1}, 0.0
        if '"facts"' in user and '"reaction"' not in user:
            return {"facts": []}, 0.0
        return dict(self.act), 0.0


def make(tmp, when=datetime(2026, 10, 29, 7, 0), names=None, world=None):
    cfg = J.load_config(tmp / "none.json")
    cfg.update(owner_discord_id="5", owner_name="Elliott")
    j = J.Jay(cfg, tmp / "data", Brain(), clock=Clock(when), rng=random.Random(5), names=names, world=world,
              library=[tmp / "nolib"])
    j.state["name"] = "Spike"
    j.state["goals"] = {"date": j._today(), "list": []}      # most tests don't want goals set first
    return j


def run(tmp):
    print("preferences can't run away")
    j = make(tmp / "a")
    j.state["prefs"] = {"being at the machine shop": 5.6, "snatch": -4.0}
    j.save()
    j2 = J.Jay(j.cfg, j.dir, Brain(), clock=j.clock, rng=random.Random(1))
    check(j2.state["prefs"] == {"being at the machine shop": 3, "snatch": -3}, "old runaway preferences are capped at ±3")
    j2.state["name"] = "Spike"
    j2.state["goals"] = {"date": j2._today(), "list": []}
    j2.brain.act = {"action": "watch", "target": "", "item": "", "why": ""}
    for _ in range(20):
        j2.shortlist = lambda st, v, acts: (["watch"], j2.urges(st, v))
        j2.tick()
    check(all(-3 <= x <= 3 for x in j2.state["prefs"].values()) and j2.state["prefs"]["watch"] > 0,
          f"20 good turns in a row stay within ±3 ({j2.state['prefs']})")

    print("boredom")
    j = make(tmp / "b")
    j.state["place"] = "junkyard"
    j.state["recent_actions"] = ["watch"] * 4
    j.brain.act = {"action": "snatch", "target": "", "item": "", "why": ""}
    for _ in range(5):
        j.shortlist = lambda st, v, acts: (["snatch"], j.urges(st, v))
        j.tick()
    check(j.state["bench"].get("snatch", 0) > j.state["tick"], "5 snatches in a row: snatch rests off the menu")
    del j.shortlist
    v = j.view(j.state)
    offered = {a for _ in range(40) for a in j.shortlist(j.state, v, j.actions(j.state, v))[0]}
    check("snatch" not in offered, "and isn't offered while it rests")
    j.state["tick"] += J.BENCH_TICKS + 1
    j.state["recent_actions"] = ["watch", "nap", "watch", "forage", "watch", "nap"]      # what an hour off snatching looks like
    offered = {a for _ in range(40) for a in j.shortlist(j.state, v, j.actions(j.state, v))[0]}
    check("snatch" in offered, "an hour later it's back")

    print("needs, the time of day and the season")
    j = make(tmp / "c", when=datetime(2026, 10, 29, 8, 0))
    st = j.state
    st["place"] = "fir"
    st["energy"] = 30
    j.inv_add(st, "black oak acorn", "food", 3)
    v = j.view(st)
    menus = [j.shortlist(st, v, j.actions(st, v))[0] for _ in range(200)]
    first = collections.Counter(m[0] for m in menus)
    check(len(menus[0]) <= J.SHORTLIST, f"he's offered at most {J.SHORTLIST} things")
    check(first["forage"] + first["eat"] + first["nap"] > 100, f"tired and it's morning: food or rest comes first most often ({dict(first)})")
    j.clock.dt = datetime(2026, 10, 29, 17, 30)
    st["energy"] = 80
    v = j.view(st)
    cache = sum("cache" in j.shortlist(st, v, j.actions(st, v))[0] for _ in range(200))
    check(cache > 120, f"a fall evening with acorns in his beak: caching is on the menu most of the time ({cache}/200)")
    st["place_since"], st["tick"] = 0, 40
    go = sum("go" in j.shortlist(st, v, j.actions(st, v))[0] for _ in range(200))
    check(go > 150, f"40 turns in one place: flying somewhere is nearly always offered ({go}/200)")
    prompt = j.decision_prompt(st, v, {"go": "fly"}, j.urges(st, v))
    check("RIGHT NOW YOU FEEL" in prompt and "restless" in prompt, "and he's told he feels restless")
    check("PLACES YOU HAVEN'T BEEN IN A WHILE" in prompt, "with places he hasn't been in a while")

    print("a stubborn brain still lives a varied day")
    j = make(tmp / "d")
    j.inv_add(j.state, "black oak acorn", "food", 4)
    did, places = collections.Counter(), set()
    for _ in range(140):                       # 7am to about 6:40pm
        j.tick()
        did[j.state["recent_actions"][-1]] += 1
        places.add(j.state["place"])
        j.clock.sleep(300)
    top, n = did.most_common(1)[0]
    check(n / sum(did.values()) < 0.4, f"no one thing more than 40% of the day (most: {top} {n}/{sum(did.values())})")
    check(len(did) >= 6, f"at least 6 different things ({dict(did)})")
    check(len(places) >= 4, f"at least 4 places ({sorted(places)})")
    check(did["cache"] >= 1, "he cached food (it's fall)")

    print("goals for the day")
    j = make(tmp / "e")
    j.state["goals"] = {"date": None, "list": []}
    j.brain.goals = [{"goal": "Fly over to the lake", "action": "go", "target": "lake"},
                     {"goal": "Be a pest", "action": "think", "target": ""},
                     {"goal": "Find something shiny", "action": "snatch", "target": ""}]
    j.brain.act = {"action": "go", "target": "lake", "item": "", "why": "goal"}
    j.shortlist = lambda st, v, acts: (["go"], j.urges(st, v))
    j.tick()
    gl = j.state["goals"]["list"]
    check([g["action"] for g in gl] == ["go", "snatch"], "he sets his goals in the morning (only real ones)")
    check(gl[0]["done"] and not gl[1]["done"], "getting to the lake ticks off that goal")
    check("one of my goals for today" in j.memories[-1]["text"], "and he remembers doing it")
    del j.shortlist
    v = j.view(j.state)
    with_goal = sum("snatch" in j.shortlist(j.state, v, j.actions(j.state, v))[0] for _ in range(100))
    j.state["goals"]["list"][1]["done"] = True
    without = sum("snatch" in j.shortlist(j.state, v, j.actions(j.state, v))[0] for _ in range(100))
    check(with_goal > without, f"an open goal is offered more often ({with_goal} vs {without} of 100)")
    check("TODAY I WANT TO:" in j.decision_prompt(j.state, v, {}, None), "his goals are in his prompt")
    j.clock.dt = datetime(2026, 10, 29, 21, 0)
    j.tick()
    check("Today I wanted to: Fly over to the lake (done)" in j.memories[-1]["text"], "falling asleep, he looks back on them")

    print("a smarter model for deciding and talking")
    j = make(tmp / "f")
    j.brain.calls = []
    j.shortlist = lambda st, v, acts: (["watch"], j.urges(st, v))
    j.brain.act = {"action": "watch", "target": "", "item": "", "why": ""}
    j.tick()
    models = [m for m, u in j.brain.calls]
    check(models[0] == "gpt-5-mini", "deciding uses gpt-5-mini")
    check(None in models[1:], "his diary line uses his everyday model")
    j.console_line("hey spike")
    check(j.brain.calls[-2][0] == "gpt-5-mini" or j.brain.calls[-1][0] == "gpt-5-mini", "talking uses gpt-5-mini")

    print("no parroting")
    j = make(tmp / "g")
    j.brain.replies = ["The blueprints sing to you, line by line, every shadow a story.",
                      "I'm guarding a brass shaving I found. Want to see it?"]
    j.console_line("The blueprints sing to me, line by line, every shadow a story.")
    check(j.state["outbox"][-1]["text"].endswith("I'm guarding a brass shaving I found. Want to see it?"),
          "a reply that repeats them gets one more try, told so")
    j.brain.replies = ["Every shadow is a story, line by line, the blueprints sing."]
    n = len(j.state["outbox"])
    j.console_line("Every shadow is a story, line by line, the blueprints sing.")
    check(len(j.state["outbox"]) == n, "if it still parrots, he says nothing")
    check(not J.echoes("Yeah? Which car?", "I rebuilt a carburetor today"), "an ordinary answer isn't an echo")

    print("names")
    j = make(tmp / "h", names={"ellwood2150": "Elliott", "i eat legos": "Caelan"})
    j.state["people"] = {"ellwood2150": {"facts": ["works on cars"], "talks": 3}}
    j.save()
    j2 = J.Jay(j.cfg, j.dir, Brain(), clock=j.clock, names={"ellwood2150": "Elliott", "i eat legos": "Caelan"})
    check(j2.state["people"] == {"Elliott": {"facts": ["works on cars"], "talks": 3}}, "people he knew by username move to their name")
    check(j2.author_name({"username": "cj_123", "global_name": "i eat legos"}) == "Caelan", "names.json works by display name too")

    print("knowing where Bolt is")
    j = make(tmp / "i")
    j.world = type("W", (), {"creature": "spike"})()
    j.state["world_view"] = {"here": [], "items": [], "cant_go": {}, "summary": "Nobody else is here.",
                             "around": [{"id": "bolt", "name": "Bolt", "place": "junkyard", "state": "awake"}]}
    v = j.view(j.state)
    check("AROUND TOWN: Bolt is at the junkyard (awake)" in j.decision_prompt(j.state, v, {}, None), "the town says where Bolt is")
    check(j.bolt_where(j.state) == {"place": "junkyard", "state": "awake"}, "and he knows it")
    alone = j.urges(j.state, v)["company"]
    j.state["world_view"]["around"] = []
    check(alone > j.urges(j.state, v)["company"], "knowing Bolt's up makes him want company a little more")
    j.state["world_view"]["around"] = [{"id": "bolt", "name": "Bolt", "place": "creek", "state": "awake"}]
    check(j.bolt_where(j.state)["place"] == "river_canyon", "the world's creek is his river canyon")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="jay_autonomy_"))
    try:
        run(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"PROBLEMS: {len(PROBLEMS)}")
    sys.exit(1 if PROBLEMS else 0)


if __name__ == "__main__":
    main()
