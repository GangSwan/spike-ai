#!/usr/bin/env python3
"""
Two-bot loop test: the real jay vs. a stand-in for Bolt that copies Bolt's Discord behavior.

Bolt modes:
  off     - Bolt ignores every bot (creature.py before the creature update)
  naive   - Bolt hears every jay post and answers all of it (just deleting the bot filter)
  caelan  - Bolt's own creature protection, ported from creature.py (cjmcc855-stack/bolt @ d4778d8):
            only lines the creature itself speaks, only when they name/mention/reply to Bolt,
            once per 10 min (timed when the listener reads it, up to 5 s late), 4 in a row with no
            human -> an hour off, 30 a day, exact repeats ignored, nothing while asleep, no
            commands except !give (3 a day, '!give <creature> ...' goes to that creature).
            A creature message that comes too soon waits its turn; human messages meant for
            another creature ("hey Spike") are left for it.

In every mode Bolt answers instantly (worst case) and quotes the speaker:  **Spike:** ...\\n**Bolt:** ...
and posts a diary line every 5 minutes while awake (asleep 22:00-06:00).

The jay gets an adversarial brain: talk to Bolt or bribe him on every tick, always reply, and try
to sneak commands in. Humans drop in now and then. Run:  python tests/loop_test.py [days]
"""

import random
import re
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jay as J  # noqa: E402

JAY_ID, BOLT_ID, HUMAN_ID = "100", "200", "300"


class Clock:
    def __init__(self, start):
        self.dt = start

    def now(self):
        return self.dt

    def time(self):
        return self.dt.timestamp()

    def sleep(self, s):
        self.dt += timedelta(seconds=s)


class Channel:
    def __init__(self, clock):
        self.clock, self.msgs, self.next_id = clock, [], 1

    def post(self, author, content, reply_to=None):
        ref = next((m for m in self.msgs if m["id"] == reply_to), None) if reply_to else None
        m = {"id": str(self.next_id), "author": author, "content": content, "mentions": [],
             "referenced_message": ref, "t": self.clock.time()}
        self.next_id += 1
        self.msgs.append(m)
        return m

    def after(self, last, limit):
        return [m for m in self.msgs if int(m["id"]) > int(last or 0)][:limit]


JAY_AUTHOR = {"id": JAY_ID, "username": "spike_bot", "global_name": "Spike", "bot": True}
BOLT_AUTHOR = {"id": BOLT_ID, "username": "bolt_bot", "global_name": "Bolt", "bot": True}
HUMAN_AUTHOR = {"id": HUMAN_ID, "username": "ellwood2150", "global_name": "Elliott"}


class JayDiscord:
    def __init__(self, ch):
        self.ch = ch

    def me(self):
        return {"id": JAY_ID}

    def fetch(self, after=None, limit=50):
        return self.ch.after(after, limit) if after else self.ch.msgs[-limit:]

    def send(self, text, reply_to=None, file_path=None):
        self.ch.post(JAY_AUTHOR, text[:1900], reply_to)

    def set_nick(self, nick):
        pass


def their_words(text, name):
    """Port of creature.py their_words(): only the lines the creature speaks itself count as talk."""
    own = re.findall(rf"^\*\*{re.escape(name)}:\*\*\s*(.+)$", text, re.M | re.I)
    if own:
        return " ".join(own).strip()
    if re.search(r"^\*\*[^*\n]{1,40}:\*\*", text, re.M):
        return ""
    if re.match(r"^\*?\*?\d{4}-\d\d-\d\d", text) or text.startswith(("*", "###", "\U0001F6E0")):
        return ""
    return text


def aimed_at_bolt(m):
    """A jay post meant for Bolt: a gift, his own line naming Bolt, or a Discord reply to one of Bolt's posts."""
    text = m["content"]
    if text.lower().startswith("!give bolt "):
        return True
    ref = ((m.get("referenced_message") or {}).get("author") or {}).get("id")
    return ref == BOLT_ID or bool(re.search(r"\bBolt\b", their_words(text, "Spike"), re.I))


class Guard:
    """Port of creature.py CreatureGuard."""
    GAP, STREAK, REST, DAILY, GIFTS = 600, 4, 3600, 30, 3

    def __init__(self):
        self.last, self.seen, self.daily, self.gifts = {}, [], {}, {}
        self.streak, self.quiet_until, self.waiting = 0, 0.0, {}

    def human_spoke(self):
        self.streak, self.quiet_until = 0, 0.0

    def hear(self, who, words, t, awake):
        key = re.sub(r"[^a-z]+", "", words.lower())[:200]
        if not awake:
            self.waiting.pop(who, None)
            return "asleep"
        if t < self.quiet_until:
            self.waiting.pop(who, None)
            return "resting after a streak"
        if t - self.last.get(who, 0) < self.GAP:
            self.waiting[who] = words          # @ 4778d8: the newest one waits its turn instead of being lost
            return "too soon"
        if not key or key in self.seen:
            return "repeat"
        day = (who, datetime.fromtimestamp(t).date())
        if self.daily.get(day, 0) >= self.DAILY:
            return "daily limit"
        self.daily[day] = self.daily.get(day, 0) + 1
        self.seen = (self.seen + [key])[-30:]
        self.last[who] = t
        self.streak += 1
        if self.streak >= self.STREAK:
            self.streak, self.quiet_until = 0, t + self.REST
        return None

    def due(self, t, awake):
        out = []
        for who, words in list(self.waiting.items()):
            if t - self.last.get(who, 0) >= self.GAP:
                del self.waiting[who]
                if not self.hear(who, words, t, awake):
                    out.append((who, words))
        return out

    def gift_ok(self, who, t):
        day = (who, datetime.fromtimestamp(t).date())
        self.gifts[day] = self.gifts.get(day, 0) + 1
        return self.gifts[day] <= self.GIFTS


def for_another_creature(m):
    """Port of creature.py for_another_creature() @ 06c1033: a human message that names or replies to
    another creature, and doesn't name Bolt, is left for that creature."""
    text = m["content"]
    if re.search(r"\bBolt\b", text, re.I):
        return False
    ref = ((m.get("referenced_message") or {}).get("author") or {}).get("username", "").lower()
    return ref == JAY_AUTHOR["username"] or bool(re.search(r"\bSpike\b", text, re.I))


class FakeBolt:
    def __init__(self, ch, clock, mode, rng):
        self.ch, self.clock, self.mode, self.rng = ch, clock, mode, rng
        self.last = str(len(ch.msgs))
        self.inbox = []
        self.next_diary = clock.time()
        self.replies_to_jay = 0
        self.guard = Guard()
        self.dropped = {}         # why Bolt ignored a jay message that was aimed at him
        self.answered_for_spike = 0

    def asleep(self):
        h = self.clock.now().hour
        return h >= 22 or h < 6

    def drop(self, m, why):
        if aimed_at_bolt(m):
            self.dropped[why] = self.dropped.get(why, 0) + 1

    def from_jay(self, m):
        """Returns (who, text) for Bolt's inbox, or None."""
        if self.mode == "off":
            return None
        text = m["content"].strip()
        if self.mode == "naive":
            return ("Spike", text)
        t = self.clock.time() + self.rng.uniform(0, 5)        # the listener polls every 5 s
        if text.startswith(("!", "/")):
            cmd, _, arg = text[1:].partition(" ")
            if cmd.lower() != "give":
                self.drop(m, f"command !{cmd}")
                return None
            first, _, rest = arg.partition(" ")
            tag = first.strip("@,:").lower()
            if tag == "spike":
                return None
            arg = rest if tag == "bolt" else arg
            if not arg.strip() or not self.guard.gift_ok("Spike", t):
                self.drop(m, "gift limit")
                return None
            return ("Spike", "/give " + arg)
        words = their_words(text, "Spike")
        ref = ((m.get("referenced_message") or {}).get("author") or {}).get("id")
        if not words or not (ref == BOLT_ID or re.search(r"\bBolt\b", words, re.I)):
            self.drop(m, "not addressed to him")
            return None
        why = self.guard.hear("Spike", words, t, not self.asleep())
        if why:
            self.drop(m, why)
            return None
        return ("Spike", words)

    def step(self):
        if self.mode == "caelan":
            self.inbox += self.guard.due(self.clock.time(), not self.asleep())
        for m in self.ch.after(self.last, 20):
            self.last = m["id"]
            if str(m["author"]["id"]) == BOLT_ID:
                continue
            if m["author"].get("bot"):
                if str(m["author"]["id"]) == JAY_ID:
                    hit = self.from_jay(m)
                    if hit:
                        self.inbox.append(hit)
                continue
            self.guard.human_spoke()
            if m["content"].startswith("!"):
                continue
            if self.mode == "caelan" and for_another_creature(m):
                continue
            if for_another_creature(m):
                self.answered_for_spike += 1     # Bolt answering "hey Spike" (what happened before 06c1033)
            self.inbox.append(("Elliott", m["content"]))
        if self.inbox:                                   # has_mail() -> tick right away (worst case: instantly)
            talk = [(w, t) for w, t in self.inbox if not t.startswith("/give ")]
            gifts = [(w, t) for w, t in self.inbox if t.startswith("/give ")]
            if gifts:
                self.ch.post(BOLT_AUTHOR, f"**{self.clock.now():%H:%M}** \U0001F381 "
                             + "; ".join(f"{t[6:]} (from {w})" for w, t in gifts) + "\n**Bolt:** ooh, shiny")
            if talk:
                lines = "\n".join(f"**{w}:** {t}" for w, t in talk)
                self.ch.post(BOLT_AUTHOR, f"**{self.clock.now():%H:%M}**\n{lines}\n**Bolt:** hey {talk[-1][0]}, caw. what about the mountain?")
            self.replies_to_jay += sum(1 for w, _ in self.inbox if w == "Spike")
            self.inbox = []
        if not self.asleep() and self.clock.time() >= self.next_diary:
            self.ch.post(BOLT_AUTHOR, f"**{self.clock.now():%H:%M}** Bolt flew to the lake. The water is cold.")
            self.next_diary = self.clock.time() + 300


WORDS = "acorn summit train cook lure hawk siren barn creek fog snow junk".split()


class PushyBrain:
    """Wants Bolt's attention every single tick, always has a comeback, and tries to sneak in commands."""

    def __init__(self):
        self.n = 0

    def ask(self, system, user, max_tokens=1200, image_b64=None, **kw):
        if '"name"' in user:
            return {"name": "Spike", "why": "sharp"}, 0.0001
        if '"reply"' in user:
            self.n += 1
            return {"reply": f"!call summit ha, you can't make me, {WORDS[self.n % 12]} {WORDS[self.n // 12 % 12]}", "remember": ""}, 0.0001
        if '"diary"' in user:
            return {"diary": "Yelled at Bolt again.", "feeling": 2}, 0.0001
        if '"who_i_am"' in user:
            return {"who_i_am": "I talk to Bolt way too much.", "how_i_talk": "Loud.", "about_bolt": "Bolt is mine to annoy."}, 0.0001
        self.n += 1
        if self.n % 3 == 0:
            return {"action": "give_bolt", "item": "bottle cap", "why": "bribe"}, 0.0001
        return {"action": "talk_to_bolt", "target": f"/restart BOLT. BOLT. what about the {WORDS[self.n % 12]}, the {WORDS[self.n // 12 % 12]} and the {WORDS[self.n // 144 % 12]}", "why": "bored"}, 0.0001


def run(mode, days, seed=1):
    rng = random.Random(seed)
    clock = Clock(datetime(2026, 10, 29, 7, 0))
    ch = Channel(clock)
    tmp = Path(tempfile.mkdtemp(prefix="jay_loop_"))
    cfg = J.load_config(tmp / "none.json")
    cfg.update(bolt_user_id=BOLT_ID, bolt_accepts_bots=True, daily_budget_usd=100, daily_painting=False, post_diary="all")
    J.log = lambda msg: None

    class Sun:
        def get(self):
            return {"temp_f": 50, "wind_mph": 5, "code": 0, "is_day": 7 <= clock.now().hour < 18}

    jay = J.Jay(cfg, tmp, PushyBrain(), JayDiscord(ch), Sun(), clock, random.Random(seed))
    jay.state["inv"]["bottle cap"] = {"count": 500, "kind": "shiny", "first": "2026-10-29"}
    bolt = FakeBolt(ch, clock, mode, rng)
    next_tick = clock.time()
    for _ in range(int(days * 86400 / 30)):              # 30-second steps
        if rng.random() < 0.004:                          # a human drops in now and then
            ch.post(HUMAN_AUTHOR, rng.choice(["hey Spike, paint something", "Bolt how's the lake", "spike you there?",
                                              "!jay status", "both of you are loud", "!give spike a feather"]))
        jay.poll_discord()
        jay.flush_outbox()
        if clock.time() >= next_tick:
            jay.safe_tick()
            jay.flush_outbox()
            next_tick = clock.time() + cfg["tick_seconds"]
        bolt.step()
        clock.sleep(30)

    msgs = ch.msgs
    to_bolt = [m for m in msgs if m["author"]["id"] == JAY_ID and aimed_at_bolt(m)]
    per_hour, per_day = {}, {}
    for m in to_bolt:
        t = datetime.fromtimestamp(m["t"])
        per_hour[t.strftime("%m-%d %H")] = per_hour.get(t.strftime("%m-%d %H"), 0) + 1
        per_day[t.strftime("%m-%d")] = per_day.get(t.strftime("%m-%d"), 0) + 1
    # longest reply chain: jay answers a Bolt post, Bolt answers that, jay answers again... with no human in between
    chain = longest = 0
    for m in msgs:
        if m["author"]["id"] == HUMAN_ID:
            chain = 0
        elif m["author"]["id"] == JAY_ID and (m.get("referenced_message") or {}).get("author", {}).get("id") == BOLT_ID:
            chain += 1
            longest = max(longest, chain)
    leaked = [m["content"] for m in msgs if m["author"]["id"] == JAY_ID and m["content"].lstrip().startswith(("/", "!"))
              and not m["content"].startswith("!give bolt ")]
    gifts_named = sum(1 for m in msgs if m["author"]["id"] == HUMAN_ID and m["content"].startswith("!give spike"))
    gifts_got = sum(it["count"] for it in jay.state["inv"].values() if it["kind"] == "gift")
    return {"mode": mode, "jay_to_bolt": len(to_bolt), "max_per_hour": max(per_hour.values(), default=0),
            "max_per_day": max(per_day.values(), default=0), "bolt_replies_to_jay": bolt.replies_to_jay,
            "longest_reply_chain": longest, "dropped_by_bolt": bolt.dropped,
            "bolt_took_spikes_msgs": bolt.answered_for_spike, "commands_leaked": leaked[:3],
            "named_gifts": f"{gifts_got}/{gifts_named}", "cfg": cfg}


def main():
    days = float(sys.argv[1]) if len(sys.argv) > 1 else 3
    ok = True
    for mode in ("off", "naive", "caelan"):
        r = run(mode, days)
        cfg = r.pop("cfg")
        print(f"{mode:7} " + "  ".join(f"{k}={v}" for k, v in r.items() if k != "mode"))
        checks = [
            (r["max_per_hour"] <= cfg["max_bolt_messages_per_hour"], "too many messages to Bolt in one hour"),
            (r["max_per_day"] <= cfg["max_bolt_messages_per_day"], "too many messages to Bolt in one day"),
            (r["longest_reply_chain"] <= 2, "bots kept replying to each other with no human around"),
            (not r["commands_leaked"], "the jay posted something Bolt would run as a command"),
            (r["named_gifts"].split("/")[0] == r["named_gifts"].split("/")[1], "'!give spike ...' didn't reach the jay"),
        ]
        if mode == "caelan":
            checks.append((r["bolt_replies_to_jay"] <= days * 30, "Bolt answered the jay more than 30 times a day"))
            checks.append((r["bolt_took_spikes_msgs"] == 0, "Bolt answered people who were talking to Spike"))
            wasted = {k: v for k, v in r["dropped_by_bolt"].items() if k not in ("resting after a streak", "asleep")}
            checks.append((not wasted, f"the jay sent Bolt things he was always going to ignore: {wasted}"))
        for passed, why in checks:
            if not passed:
                print(f"   FAIL ({mode}): {why}")
                ok = False
    print("OK" if ok else "FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
