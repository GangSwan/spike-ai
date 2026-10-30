#!/usr/bin/env python3
"""
Bolt's Oct 29 changes, Spike's way: noticing who's around, knowing who Bolt is, remembering his own past,
things left for someone else, honest wins, Discord catch-up after a restart, and the long build puzzle
(plans from reading, parts he has to go find, builds that change his life, fixer-uppers).

    python tests/town_test.py
"""

import random
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
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
    def __init__(self):
        self.act = {"action": "watch", "target": "", "item": "", "why": "felt like it"}
        self.feeling = 1
        self.prompts = []

    def ask(self, system, user, max_tokens=1200, image_b64=None, **kw):
        self.prompts.append(user)
        if '"goals"' in user:
            return {"goals": []}, 0.0
        if '"reply"' in user:
            return {"reply": "Saw him at the creek."}, 0.0
        if '"diary"' in user:
            return {"diary": "Did a thing.", "feeling": self.feeling}, 0.0
        if '"reaction"' in user:
            return {"reaction": "Neat.", "words": [], "facts": ["gears mesh by their teeth"], "topic": "machines"}, 0.0
        if '"discovery"' in user:
            return {"new": True, "discovery": "It's smooth.", "fact": "it's smooth on one side", "topic": "machines"}, 0.0
        if '"facts"' in user:
            return {"facts": []}, 0.0
        return dict(self.act), 0.0


class Lucky(random.Random):
    def random(self):
        return 0.0          # every roll succeeds


class Discord:
    def __init__(self, msgs):
        self.msgs, self.sent = msgs, []

    def me(self):
        return {"id": "999"}

    def fetch(self, after=None, limit=50):
        out = [m for m in self.msgs if after is None or int(m["id"]) > int(after)]
        return out[:limit]

    def send(self, text, reply_to=None, file_path=None):
        self.sent.append(text)


def make(tmp, rng=None, when=datetime(2026, 10, 30, 10, 0)):
    cfg = J.load_config(tmp / "none.json")
    cfg.update(owner_discord_id="5", owner_name="Elliott")
    j = J.Jay(cfg, tmp / "data", Brain(), clock=Clock(when), rng=rng or random.Random(4), library=[tmp / "nolib"])
    j.state["name"] = "Spike"
    j.state["goals"] = {"date": j._today(), "list": []}
    return j


def in_world(j, here=(), items=()):
    j.world = type("W", (), {"creature": "spike"})()
    j.state["world_view"] = {"here": list(here), "items": list(items), "cant_go": {}, "summary": "", "around": []}


def act(j, action, target="", item=""):
    """One turn; returns what happened and the diary feeling he kept."""
    j.brain.act = {"action": action, "target": target, "item": item, "why": "felt like it"}
    j.shortlist = lambda st, v, acts: (([action] if action in acts else []) + [a for a in acts if a != action], j.urges(st, v))
    j.tick()
    seen = [p for p in j.brain.prompts if "WHAT HAPPENED: " in p]
    return seen[-1].split("WHAT HAPPENED: ", 1)[1].split("\n")[0] if seen else ""


def do(j, action, target="", item=""):
    """Just the action, on his state (no model turn around it)."""
    text, special, cost = j.execute(j.state, {"action": action, "target": target, "item": item, "why": ""}, j.view(j.state))
    return text


def run(tmp):
    print("noticing who's around")
    j = make(tmp / "a")
    in_world(j, [{"id": "bolt", "name": "Bolt", "state": "awake", "doing": "fishing"}])
    j.state["place"] = "lake"
    seen = j.notice_company(j.state)
    check(seen == "Bolt is here at the lake, awake, fishing", f"Bolt shows up ({seen})")
    check(j.state["fellows"]["Bolt"]["seen_at"] == "lake", "and he remembers where he last saw him")
    check(j.notice_company(j.state) == "", "nothing new, nothing noticed")
    j.state["world_view"]["here"][0]["state"] = "asleep"
    check(j.notice_company(j.state) == "Bolt fell asleep", "Bolt dozes off")
    j.state["world_view"]["here"] = []
    check(j.notice_company(j.state) == "Bolt left the lake", "Bolt leaves")
    j.state["world_view"]["here"] = [{"id": "bolt", "name": "Bolt", "state": "awake", "doing": None}]
    j.state["place"] = "fir"
    check(j.notice_company(j.state).startswith("Bolt is here at the old fir"), "somewhere new, it's an arrival again")
    j.brain.prompts.clear()
    j.world_look, j.world_settle, j.world_queue = (lambda st: None), (lambda: None), (lambda st, action, **f: None)
    act(j, "watch")
    check(any("I saw: Bolt" in m["text"] for m in j.memories) is False, "already noticed: no repeat memory")
    j.state["world_view"]["here"][0]["state"] = "asleep"
    act(j, "watch")
    check(any(m["text"] == "I saw: Bolt fell asleep." for m in j.memories), "a turn remembers what he noticed")
    check(any("NEW: You notice: Bolt fell asleep." in p for p in j.brain.prompts), "and his turn hears about it")

    print("knowing who Bolt is")
    j = make(tmp / "b")
    facts = j.fellow_facts(j.state, "what do you think of Bolt?")
    check("Bolt: a young crow, Caelan's creature, lives at Bolt's nest." in facts, f"plain facts about Bolt ({facts.strip()[-80:]})")
    check(j.fellow_facts(j.state, "how's the weather up there") == "", "talk that isn't about him doesn't bring him up")
    check("Bolt:" in j.fellow_facts(j.state, "is your friend around?"), "'your friend' means Bolt")
    check("Bolt:" in j.fellow_facts(j.state, "what's Caelan's bird up to"), "so does Caelan's bird")
    j.state["fellows"]["Bolt"] = {"seen": "2026-10-28T09:00:00", "seen_at": "river_canyon"}
    j.remember_talk(j.state, "Bolt", "Caught a trout!", "Nice. How big?")
    facts = j.fellow_facts(j.state, "seen bolt lately?")
    check("you last saw him at the river canyon on oct 28" in facts.lower(), "when and where he last saw him")
    check('Bolt said "Caught a trout!" and you said "Nice. How big?"' in facts, "and their last talk")
    check("Caught a trout" not in j.fellow_facts(j.state, "hi", talking_to="Bolt"), "talking to Bolt, the talk isn't repeated")
    j.state["fellows"] = {}
    j.remember(j._mem(j.state, "2026-10-29T10:00:00", "talk", 'Bolt said "Riff time" and I said "Go for it"', 1, True))
    check('Bolt said "Riff time"' in j.fellow_facts(j.state, "bolt?"), "older talks come from the memory book")
    j.discord = Discord([])
    j.me_id = "999"
    j.reply({"id": "7"}, "Elliott", "what do you think of Bolt?", False)
    asked = [p for p in j.brain.prompts if "just said to you" in p][-1]
    check("WHAT YOU THINK OF BOLT:" in asked and "Caelan's creature" in asked,
          "asked about Bolt on Discord, he answers from what he thinks and what he knows")

    print("remembering his own past")
    j = make(tmp / "c")
    for i, text in enumerate(["Cached a black oak acorn under the fir roots.", "Snatched a silver ring at the junkyard.",
                              "Practiced my train horn at the rail yard.", "Found a sugar pine nut on the trail."]):
        j.remember(j._mem(j.state, f"2026-10-2{i}T09:00:00", "x", text, 1, True))
    got = j.remember_past("do you remember the silver ring?")
    check(len(got) == 1 and "silver ring" in got[0], f"asked, he finds the moment ({got})")
    check(j.remember_past("nice weather") == [], "nothing connects, nothing comes up")
    check(j.remember_past("acorn") == [], "unasked, one word isn't enough")
    check("FROM YOUR MEMORY BOOK" in j.past_lines(j.state, "ever cached an acorn?"), "it goes in his reply prompt")

    print("things left for someone else")
    j = make(tmp / "d")
    in_world(j, items=[{"id": "b1", "name": "For Bolt: blueprint of a sequential gearbox", "by": "Caelan", "for": "bolt"},
                       {"id": "i2", "name": "bottle cap", "by": "Bolt", "for": None}])
    prompt = j.decision_prompt(j.state, j.view(j.state), {}, None)
    check("LEFT HERE FOR SOMEONE ELSE" in prompt and "(for Bolt)" in prompt, "he sees Caelan's blueprint is for Bolt")
    check([i["name"] for i in j.world_items(j.state)] == ["bottle cap"], "and can't pick it up")

    print("only real wins count")
    check(J.didnt_happen("You hopped around but stayed at the old fir.") and J.didnt_happen("You wanted to build the zipline, but x"),
          "wanting to isn't doing")
    check(not J.didnt_happen("You snatched a bottle cap at the junkyard."), "doing is doing")
    j = make(tmp / "e")
    j.brain.feeling = 2
    act(j, "go", "fir")
    check(j.memories[-1]["feeling"] <= 0, "staying put can't make him happy")
    act(j, "go", "lake")
    check(j.memories[-1]["feeling"] == 2, "really flying somewhere can")

    print("Discord after a restart")
    now = datetime(2026, 10, 30, 10, 0)
    old = (now - timedelta(hours=3)).replace(tzinfo=timezone.utc).astimezone().isoformat()
    j = make(tmp / "f", when=now)
    j.state["discord_cursor"] = "10"
    j.discord = Discord([{"id": "11", "author": {"id": "5", "username": "ellwood2150"}, "content": "!jay paint the barn",
                          "timestamp": (now - timedelta(hours=3)).astimezone().isoformat()},
                         {"id": "12", "author": {"id": "5", "username": "ellwood2150"}, "content": "!jay paint the lake",
                          "timestamp": now.astimezone().isoformat()}])
    j.poll_discord()
    subjects = [p["subject"] for p in j.state["paint_queue"]]
    check(subjects == ["the lake"], f"he catches up, but a 3-hour-old command is let go ({subjects})")
    check(J.load_json(j.state_path, {})["discord_cursor"] == "12", "the cursor is saved past what he read")
    j = make(tmp / "g")
    j.state["discord_cursor"] = "10"
    j.discord = Discord([{"id": "11", "author": {"id": "5", "username": "ellwood2150"}, "content": "!jay restart"}])
    saved = []
    j.command = lambda m, who, content, console=False: saved.append(J.load_json(j.state_path, {})["discord_cursor"])
    j.poll_discord()
    check(saved == ["11"], "a command is saved as read before it runs, so a restart never replays it")

    print("plans: reading gives him the idea")
    j = make(tmp / "h", rng=Lucky())
    check(j.plan_idea(j.state, "Galileo built a telescope.").startswith(" (That gave you an idea: you could build a spyglass yourself"),
          "reading about a telescope")
    check(j.my_plans(j.state) == ["spyglass"] and j.plan_idea(j.state, "another telescope") == "", "once")
    check("build" in j.actions(j.state, j.view(j.state)), "build is on his list now")
    j.state["place"] = "ambulance_station"
    check("haven't worked out your plan" in do(j, "build", "spyglass"), "not studied, not built")
    out = do(j, "snatch")
    check("magnifying lens" not in out, "he doesn't find a part he doesn't know he needs")
    steps = [do(j, "examine", item="the spyglass plan") for _ in range(5)]
    check("calls for a magnifying lens (one turns up at the ambulance station)" in steps[0], f"studying, one thing at a time ({steps[0]})")
    check("gets built at the junkyard" in steps[3] and "already know everything" in steps[4], "until he knows it all")
    check(j.state["notebooks"]["machines"][0].startswith("spyglass: calls for a magnifying lens"), "it goes in his machines notebook")
    check("found a magnifying lens" in do(j, "snatch"), "knowing, he finds the part where it turns up")
    check(j.wanted_parts(j.state) == [("cardboard tube", "diner_roof"), ("strip of black tape", "garage")], "and knows what's still missing")
    j.state["place"] = "junkyard"
    check("still missing: cardboard tube, strip of black tape" in do(j, "build", "spyglass"), "missing parts, plainly")
    j.inv_add(j.state, "cardboard tube", "part")
    j.inv_add(j.state, "strip of black tape", "part")
    check("don't understand the magnifying lens" in do(j, "build", "spyglass"), "every part has to be understood")
    for part in ("magnifying lens", "cardboard tube", "strip of black tape"):
        do(j, "examine", item=part)
    J.JOBS["spyglass"]["level"] = 11
    check("tinkering isn't up to it" in do(j, "build", "spyglass"), "and enough tinkering")
    J.JOBS["spyglass"]["level"] = 2
    j.state["skills"]["tinker"] = 999
    snatch_before = j._level(j.state, "snatch")
    out = do(j, "build", "spyglass")
    check(out.startswith("You built the spyglass! Now you spot shiny things"), f"built ({out[:60]})")
    check(j._level(j.state, "snatch") == min(10, snatch_before + 2), "and snatching gets better")
    check(not j.inv_of(j.state, {"part"}) and "build" not in j.actions(j.state, j.view(j.state)), "parts used, no plans left")

    print("bigger builds need smaller ones")
    j.plan_idea(j.state, "a pinhole camera obscura")
    j.state["plans"]["obscura"]["learned"] = 99
    j.state["place"] = "fir"
    for part in ("shoebox", "sheet of wax paper"):
        j.inv_add(j.state, part, "part")
        j.state["item_lore"][part] = {"facts": ["paper"], "done": False}
    j.state["built"]["spyglass"]["in"] = "x"
    check("needs a working spyglass first" in do(j, "build", "camera obscura"), "the camera obscura needs the spyglass")
    del j.state["built"]["spyglass"]["in"]
    paint = j.machine_bonus(j.state, "paint")
    check("built the camera obscura" in do(j, "build", "obscura"), "with it, it goes together")
    check(j.state["built"]["spyglass"]["in"] == "obscura" and not j.working(j.state, "spyglass"), "the spyglass is inside it now")
    check(j.machine_bonus(j.state, "paint") == paint + 1, "and his painting gets better")

    print("builds change his life")
    j = make(tmp / "i")
    j.state["built"] = {"zipline": {"when": "x"}, "locker": {"when": "x"}}
    j.state["place"] = "mountain_trail"
    out = do(j, "go", "summit")
    check(out.startswith("You rode your zipline from the mountain trail to the summit"), f"the zipline ({out[:50]})")
    j.state["caches"] = [{"id": 1, "place": "fir", "food": "peanut", "forgotten": False, "t": j.clock.time()}]
    j.rng = Lucky()
    j._daily_forgetting(j.state, j.view(j.state))
    check(not j.state["caches"][0]["forgotten"], "food in the acorn locker is never forgotten")

    print("fixer-uppers")
    j = make(tmp / "j", rng=Lucky())
    j.state["place"] = "shed"
    check(j.spot_fixer(j.state) is None, "knowing nothing about machines, a broken radio is just junk")
    j.state["skills"]["tinker"] = 999
    j.note(j.state, "machines", "a spring stores energy when you wind it")
    out = do(j, "snatch")
    check("came across a dead transistor radio" in out, f"knowing a bit, he sees it could work ({out[:70]})")
    check("haven't worked out everything that's wrong" in do(j, "build", "radio"), "first he finds what's wrong")
    first = do(j, "examine", "radio")
    check("the battery clip is corroded, so it needs a battery clip" in first, f"one thing per look ({first[:80]})")
    do(j, "examine", "radio")
    check("that's everything wrong with it" in do(j, "examine", "radio"), "until he's found it all")
    for part in ("battery clip", "dial cord"):
        j.inv_add(j.state, part, "part")
        j.state["item_lore"][part] = {"facts": ["small"], "done": False}
    out = do(j, "build", "radio")
    check(out.startswith("You got the dead transistor radio working again!"), f"fixed ({out[:60]})")
    check("radio jingle" in j.learnable_sounds(j.state), "and there's a new sound to learn in the shed")
    j.state["place"] = "old_barn"
    j.state["plans"]["musicbox"] = {"learned": 0}
    out = do(j, "take_apart", item="music box")
    check(out.startswith("You stripped the broken music box for parts") and j.state["plans"]["musicbox"]["stripped"],
          "or he can strip one for parts")
    check("musicbox" not in j.my_plans(j.state), "and then it's gone")

    print("starting a conversation is remembered")
    j = make(tmp / "k")
    in_world(j, [{"id": "bolt", "name": "Bolt", "state": "awake", "doing": None}])
    j.world_queue = lambda st, action, **f: None
    do(j, "talk", "Found a ring today.")
    check(j.state["fellows"]["Bolt"]["lately"][-1]["me"] == "Found a ring today.", "what he said to Bolt is kept")
    check('you said to Bolt: "Found a ring today."' in j.fellow_facts(j.state, "what's bolt up to"), "and comes back later")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="jay_town_"))
    try:
        run(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"PROBLEMS: {len(PROBLEMS)}")
    sys.exit(1 if PROBLEMS else 0)


if __name__ == "__main__":
    main()
