#!/usr/bin/env python3
"""
Bolt's habits in the jay: books, looking things up, notebooks, studying his things, changing his mind,
tinkering, painting on his own, plain talk, remembering people, gift reactions, ruts, calls, being woken
at night, the console, book orders and tested restarts. A scripted brain, so every check is exact.

    python tests/habits_test.py
"""

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
    """Answers by what the prompt asks for."""

    def __init__(self):
        self.act = {"action": "watch", "target": "", "item": "", "why": ""}
        self.reply = "Hah."
        self.feeling = 0
        self.n = 0
        self.prompts = []

    def ask(self, system, user, max_tokens=1200, image_b64=None, **kw):
        self.prompts.append(user)
        self.n += 1
        if '"reaction"' in user and '"facts"' in user:
            return {"reaction": "Huh. Neat.", "words": ["swarf"], "facts": ["obsidian breaks with curved, sharp edges"],
                    "topic": "rocks"}, 0.0
        if '"wrong"' in user:
            return {"wrong": [0], "now_you_know": "it's aluminum, not steel"}, 0.0
        if '"discovery"' in user:
            return {"new": True, "discovery": "It rattles when I shake it.", "fact": f"it has a seam number {self.n}",
                    "topic": "machines"}, 0.0
        if '"what_it_does"' in user:
            return {"name": "pin whistle", "what_it_does": "it whistles when the wind blows through it"}, 0.0
        if '"facts"' in user:
            return {"facts": ["works as a mechanic"]}, 0.0
        if '"plain"' in user:
            return {"plain": "It's a good lake."}, 0.0
        if '"reply"' in user:
            return {"reply": self.reply}, 0.0
        if '"reflection"' in user:
            return {"reflection": "I was a lot dumber then."}, 0.0
        if '"reaction"' in user:
            return {"reaction": "A peanut! Mine."}, 0.0
        if '"diary"' in user:
            return {"diary": "Did a thing.", "feeling": self.feeling}, 0.0
        return dict(self.act), 0.0


class Web:
    def wiki(self, topic):
        return "Obsidian", "Obsidian is volcanic glass. It breaks with curved, very sharp edges."

    def book(self, query):
        return "Moby Dick", "Herman Melville", "Call me Ishmael. " * 400


class Lucky(random.Random):
    def random(self):
        return 0.0          # every roll succeeds


def make(tmp, hour=10, rng=None):
    lib = tmp / "lib"
    lib.mkdir(parents=True, exist_ok=True)
    (lib / "Field_Guide_to_Rocks.txt").write_text(
        "ROCKS\n\nObsidian is black volcanic glass.\n\n" + "Pumice floats on water. " * 200, encoding="utf-8")
    cfg = J.load_config(tmp / "none.json")
    cfg.update(owner_discord_id="5", owner_name="Elliott")
    j = J.Jay(cfg, tmp / "data", Brain(), clock=Clock(datetime(2026, 10, 29, hour, 0)), rng=rng or random.Random(3),
              web=Web(), library=[lib, tmp / "data" / "library"])
    j.state["name"] = "Spike"
    return j


def act(j, action, target="", item=""):
    """One turn; returns what happened (the outcome his reaction prompt was shown)."""
    j.brain.act = {"action": action, "target": target, "item": item, "why": "felt like it"}
    # these tests are about what an action does, so it's always on his menu (the menu has its own tests)
    j.shortlist = lambda st, v, acts: (([action] if action in acts else []) + [a for a in acts if a != action], j.urges(st, v))
    out = j.tick()
    seen = [p for p in j.brain.prompts if "WHAT HAPPENED: " in p]
    return f"{out.split(' ', 1)[0]} {seen[-1].split('WHAT HAPPENED: ', 1)[1].split(chr(10))[0]}" if seen else out


def main():
    tmp = Path(tempfile.mkdtemp(prefix="jay_habits_"))
    try:
        run(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"PROBLEMS: {len(PROBLEMS)}")
    sys.exit(1 if PROBLEMS else 0)


def run(tmp):
    print("books and notebooks")
    j = make(tmp / "a")
    out = act(j, "read", "rocks")
    st = j.state
    check("read a bit of Field Guide to Rocks" in out, "he reads the book he asked for")
    check("obsidian breaks with curved, sharp edges" in st["notebooks"].get("rocks", []), "the fact goes in his rocks notebook")
    check("swarf" in st["words"], "a word he liked joins his vocabulary")
    check(st["books"]["Field_Guide_to_Rocks.txt"] > 0, "he remembers where he stopped")
    check(st["skills"]["snatch"] == 1, "studying rocks trains snatching")
    before = st["books"]["Field_Guide_to_Rocks.txt"]
    act(j, "read", "")
    check(st is not j.state and j.state["books"]["Field_Guide_to_Rocks.txt"] > before, "next time he reads on from there")
    out = act(j, "read", "dragons")
    check("none of them cover it" in out and "look it up" in out, "a book he doesn't have: he says so")
    out = act(j, "look_up", "obsidian")
    check("looked up obsidian and read about Obsidian" in out, "look_up reads the big book of everything")
    prompt = j.decision_prompt(j.state, j.view(j.state), j.actions(j.state, j.view(j.state)))
    check("MY NOTEBOOKS: rocks" in prompt and "MY BOOKS: Field Guide to Rocks" in prompt, "his notebooks and books are in his prompt")
    check("WORDS I'VE PICKED UP: swarf" in prompt, "so are his new words")
    for _ in range(4):
        j.note(j.state, "rocks", f"rock fact {_}")
    check(j._level(j.state, "snatch") == J.skill_level(j.state["skills"]["snatch"]) + 1, "5 rock notes = one bonus snatch level")

    print("studying his things")
    j.inv_add(j.state, "chrome screw", "shiny")
    for _ in range(5):
        act(j, "examine", item="chrome screw")
    lore = j.state["item_lore"]["chrome screw"]
    check(len(lore["facts"]) == 5 and lore["done"], "five discoveries and he's mastered it")
    out = act(j, "examine", item="chrome screw")
    check("inside and out" in out, "then there's nothing left to study")
    check(any(f.startswith("chrome screw: ") for f in j.state["notebooks"]["machines"]), "discoveries go in his notebooks")
    j.state["item_lore"]["wheel spacer"] = {"facts": ["it's made of steel"], "done": False}
    j.state["notebooks"]["machines"].append("wheel spacer: it's made of steel")
    said = j.learn(j.state, "read", "a car book", "Wheel spacers are almost always aluminum.")
    lore = j.state["item_lore"]["wheel spacer"]
    check(lore["facts"] == ["it's aluminum, not steel"] and lore["used_to_think"] == ["it's made of steel"],
          "reading proves him wrong: he fixes it and remembers what he used to think")
    check("wheel spacer: it's made of steel" not in j.state["notebooks"]["machines"], "the wrong note leaves his notebook")
    check("I used to think" in said, "and he says so")

    print("tinkering")
    j = make(tmp / "b", rng=Lucky(1))
    st = j.state
    st["place"] = "garage"
    j.inv_add(st, "bent nail", "shiny")
    j.inv_add(st, "bottle cap", "shiny")
    j.inv_add(st, "red bobber from Elliott", "gift", from_="Elliott")
    check("tinker" in j.actions(st, j.view(st)), "he can tinker at the garage with two shiny things")
    act(j, "tinker", item="bent nail + bottle cap")
    st = j.state
    inv = [n for n, it in st["inv"].items() if it["kind"] == "invention"]
    check(inv == ["pin whistle (made from bent nail + bottle cap)"], "he builds something out of them")
    check("bent nail" not in st["inv"] and "bottle cap" not in st["inv"], "the parts are used up")
    check("red bobber from Elliott" in st["inv"], "the gift is never touched")
    check(st["skills"]["tinker"] == 2, "building trains tinkering")
    act(j, "take_apart", item="pin whistle")
    st = j.state
    check("bent nail" in st["inv"] and "bottle cap" in st["inv"] and not j.inv_of(st, {"invention"}),
          "taking it apart gives the parts back")
    j.inv_take(st, "bent nail")
    check("tinker" not in j.actions(j.state, j.view(j.state)), "one shiny thing and a gift: nothing to tinker with")
    out = j._do_tinker(j.state, {"action": "tinker", "target": "", "item": "bottle cap + red bobber", "why": ""},
                       j.view(j.state))[0]
    check("enough junk" in out and "red bobber from Elliott" in j.state["inv"], "a gift can't be built into anything")

    print("ruts and getting stuck")
    j = make(tmp / "c")
    st = j.state
    st["recent_actions"] = ["forage"] * 4
    st["recent_feelings"] = [0, -1, 0, -1]
    st["fail_streak"] = {"action": "snatch", "n": 3}
    prompt = j.decision_prompt(st, j.view(st), j.actions(st, j.view(st)))
    check("RUT: you've done forage 4 turns in a row" in prompt, "a rut is pointed out plainly")
    check("STUCK: your last 3 tries at snatch" in prompt and "Field Guide to Rocks" in prompt,
          "so is a losing streak, with a book that could help")
    st["recent_feelings"] = [1, 1, 1, 1]
    check(j.rut_note(st) == "", "doing a thing he enjoys isn't a rut")

    print("painting on his own")
    j = make(tmp / "d")
    act(j, "paint", "the lake at dawn")
    check([q["kind"] for q in j.state["paint_queue"]] == ["own"] and j.state["paint_queue"][0]["subject"] == "the lake at dawn",
          "he decides to paint, and it goes in the queue")
    check("paint" not in j.actions(j.state, j.view(j.state)), "one of his own at a time")
    j.state["paint_queue"] = []
    j.state["own_paints"] = {j._today(): 3}
    check("paint" not in j.actions(j.state, j.view(j.state)), "and at most 3 of his own a day")

    print("talking")
    j = make(tmp / "e")
    j.brain.reply = ("The lake is a serene, magical mirror, like a dream. It shimmers like a jewel. The breeze dances "
                     "across the surface like a ribbon of light. Truly a tapestry of wonder for any bird to behold.")
    j.console_line("I work on cars all day. How's the lake?")
    st = j.state
    check(st["outbox"][-1]["text"].endswith("**Spike:** It's a good lake."), "a flowery reply gets said again plainly")
    check(st["convo"][-1]["reply"] == "It's a good lake.", "the conversation is remembered")
    check(st["people"]["Elliott"]["facts"] == ["works as a mechanic"], "what Elliott said about himself is kept")
    j.brain.reply = "Yeah? Which car?"
    j.console_line("Rebuilt a carburetor today")
    asked = [p for p in j.brain.prompts if "Rebuilt a carburetor" in p and '"reply"' in p][-1]
    check("YOUR PAST CONVERSATIONS" in asked and "Don't start the way your recent replies started" in asked,
          "the next reply sees the history and avoids starting the same way")
    energy = st["energy"] = 50
    j.console_line("!give peanut")
    check(st["energy"] == energy + 15 and "peanut from Elliott" in st["inv"], "a food gift feeds him and stays in his hoard")
    check(st["outbox"][-1]["text"] == "**Spike:** A peanut! Mine.", "and he reacts to it")

    print("calls")
    j = make(tmp / "f")
    j.command({"id": "1", "author": {"id": "77", "username": "stranger"}}, "stranger", "!jay call lake")
    check(j.state["call"] is None and "only comes when Elliott calls" in j.state["outbox"][-1]["text"],
          "only his owner can call him")
    j.console_line("!call lake")
    check(j.state["call"]["place"] == "lake" and j.soon, "his owner calls him and he hears it right away")
    act(j, "watch")
    check(j.state["place"] == "lake" and "👋" in j.state["outbox"][-1]["text"], "he flies over")
    check("so you flew there to be with them" in j.brain.prompts[-2], "his turn knows who called him")
    j.console_line("!call summit")
    act(j, "watch")
    check(j.state["place"] == "summit" and "mountain_trail" in j.state["visited"], "to the summit, he goes by the trail")
    check(j.named_command("!call spike fir") == "!jay call fir", "Bolt's style works too: !call spike <place>")

    print("night")
    j = make(tmp / "g", hour=23)
    check(j.tick() == "fell asleep" and j.tick() == "asleep", "he sleeps at night")
    j.console_line("hey, you awake?")
    check(j.soon, "a human talking wakes him")
    out = act(j, "watch")
    check(out.startswith("watch") and not j.state["asleep"], "and he gets up for them")
    check("woke you up in the middle of the night" in j.brain.prompts[-2], "knowing why he's up")
    j.clock.sleep(25 * 60)
    check(j.tick() == "fell asleep", "20 minutes after they go quiet, back to sleep")

    print("books by request, restarts")
    j = make(tmp / "h")
    j.console_line("!jay book moby dick")
    j.fetch_books()
    check("Moby_Dick.txt" in j.books() and "New book" in j.state["outbox"][-1]["text"], "!jay book puts it in his library")
    j.command({"id": "2", "author": {"id": "77", "username": "stranger"}}, "stranger", "!jay restart")
    check(not j.restart_wanted, "only his owner can restart him")
    (j.dir / "restart.flag").touch()
    j.new_code_ok = lambda: (False, "sim_days.py: FAILED")
    check(not j.restart_due() and "restart cancelled" in j.state["outbox"][-1]["text"], "broken new code: no restart")
    check(not (j.dir / "restart.flag").exists(), "the flag is used up")
    j.new_code_ok = lambda: (True, "")
    j.console_line("!jay restart")
    check(j.restart_due(), "good new code: he restarts")


if __name__ == "__main__":
    main()
