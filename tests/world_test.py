#!/usr/bin/env python3
"""
Spike in shasta-world: the real server (from a shasta-world checkout) in test mode, the real Spike
with a scripted brain, and a scripted Bolt using the same world_client.py.

    python tests/world_test.py                    # looks for shasta-world next to this repo
    SHASTA_WORLD=C:\\dev\\shasta-world python tests/world_test.py
"""

import copy
import os
import random
import shutil
import socket
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
WORLD_REPO = Path(os.environ.get("SHASTA_WORLD", HERE.parent.parent / "shasta-world"))
if not (WORLD_REPO / "world" / "server.py").exists():
    sys.exit(f"Can't find shasta-world at {WORLD_REPO}. Clone it next to this repo or set SHASTA_WORLD.")
sys.path.insert(0, str(WORLD_REPO))

import jay as J  # noqa: E402
from sim_days import ChaosBrain, FakeClock  # noqa: E402
from world.server import TEST_ROSTER, Server, World  # noqa: E402
from world_client import WorldClient  # noqa: E402


class ScriptBrain:
    """Says whatever the test lines up next; otherwise watches."""

    def __init__(self):
        self.plan, self.prompts = [], []

    def ask(self, system, user, max_tokens=1200, image_b64=None):
        self.prompts.append(user)
        if '"reply"' in user:
            return {"reply": "Caw yourself, Bolt."}, 0.0
        if '"diary"' in user:
            return {"diary": "Did a thing.", "feeling": 1}, 0.0
        if '"who_i_am"' in user:
            return {"who_i_am": "A jay who lives in a shared town now.", "how_i_talk": "Loud.",
                    "about_bolt": "Bolt is right there, a crow."}, 0.0
        if self.plan:
            return self.plan.pop(0), 0.0
        return {"action": "watch", "target": "", "item": "", "why": "looking"}, 0.0


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db, self.port = str(self.tmp / "world.db"), free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.server = None
        self.up()
        self.clock = FakeClock(datetime(2026, 10, 29, 10, 0))
        self.brain = ScriptBrain()
        self.spike = self.make_spike()
        self.bolt, self.bws = WorldClient(self.url, "test-bolt", "bolt", timeout=1, retry=(0, 0)), {}

    def tearDown(self):
        if self.server:
            self.server.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def up(self):
        self.server = Server(World(self.db, TEST_ROSTER, test=True), port=self.port, background=False).start()

    def down(self):
        self.server.stop()
        self.server = None

    def make_spike(self, brain=None):
        cfg = J.load_config(self.tmp / "no-config.json")
        cfg["daily_painting"] = False
        wc = WorldClient(self.url, "test-spike", "spike", timeout=1, retry=(0, 0))
        jay = J.Jay(cfg, self.tmp / "spike", brain or self.brain, clock=self.clock, rng=random.Random(1), world=wc)
        if not jay.state["name"]:
            jay.state["name"] = "Spike"
            jay.save()
        return jay

    def restart_spike(self):
        """A power cut and a restart: a new process that only has what's on disk."""
        self.spike = self.make_spike()

    def bolt_at(self, place):
        return self.bolt.look(self.bws, place, True)

    def bolt_does(self, action, **fields):
        self.bolt.queue(self.bws, action, **fields)
        return self.bolt.send(self.bws)

    def plan(self, action, target="", item=""):
        self.brain.plan.append({"action": action, "target": target, "item": item, "why": "test"})

    def tick(self, minutes=5):
        what = self.spike.tick()
        self.clock.sleep(minutes * 60)
        return what


class Basics(Base):
    def test_off_means_his_old_life(self):
        cfg = J.load_config(self.tmp / "no-config.json")
        jay = J.Jay(cfg, self.tmp / "off", ScriptBrain(), clock=self.clock)
        acts = jay.actions(jay.state, jay.view(jay.state))
        self.assertFalse({"talk", "give", "pick_up"} & set(acts))
        self.assertEqual(jay.state["world"], {})

    def test_he_appears_in_the_world_at_his_fir(self):
        self.tick()
        seen = self.bolt_at("fir")
        self.assertEqual([(h["id"], h["state"]) for h in seen["here"]], [("spike", "awake")])

    def test_sees_bolt_and_talks_to_him(self):
        self.bolt_at("fir")
        self.tick()
        acts = self.spike.actions(self.spike.state, self.spike.view(self.spike.state))
        self.assertIn("talk", acts)
        self.assertNotIn("talk_to_bolt", acts)          # the Discord way is off in the world
        self.assertIn("Bolt is here", self.brain.prompts[-2] + self.brain.prompts[-1])
        self.plan("talk", "Hey Bolt, nice nest.")
        self.tick()
        heard = self.bolt.heard(self.bws)
        self.assertEqual([(h["from"], h["to"], h["text"]) for h in heard], [("spike", "bolt", "Hey Bolt, nice nest.")])

    def test_answers_bolt_between_ticks(self):
        self.tick()
        self.bolt_at("fir")
        self.bolt_does("say", text="Spike! What are you hiding up there?", to="spike")
        self.spike.world_poll()
        heard = self.bolt.heard(self.bws)
        self.assertEqual([(h["from"], h["text"]) for h in heard], [("spike", "Caw yourself, Bolt.")])
        self.assertTrue(self.spike.state["outbox"][-1]["text"].startswith("**2026"))   # narration for Discord
        self.assertIn("Bolt said", self.spike.memories[-1]["text"])

    def test_river_canyon_is_the_creek(self):
        self.tick()
        self.plan("go", "river canyon")
        self.tick()
        self.assertEqual(self.spike.state["place"], "river_canyon")
        self.assertEqual(self.bolt_at("creek")["here"][0]["id"], "spike")

    def test_the_summit_rule_holds(self):
        self.spike.state["place"] = "lake"
        self.spike.save()
        self.tick()
        self.plan("go", "summit")
        self.tick()
        self.assertEqual(self.spike.state["place"], "lake")
        self.assertIn("mountain_trail", self.spike.memories[-1]["text"] + self.brain.prompts[-1])

    def test_sleeps_and_wakes_in_the_world(self):
        self.spike.state["place"] = "lake"
        self.spike.save()
        self.tick()
        self.bolt_at("fir")
        self.clock.dt = datetime(2026, 10, 29, 21, 0)
        self.tick()
        seen = self.bolt.look(self.bws, "fir", True)
        self.assertEqual([(h["id"], h["state"]) for h in seen["here"]], [("spike", "asleep")])
        self.clock.dt = datetime(2026, 10, 30, 8, 0)
        self.tick()
        self.assertEqual(self.bolt.look(self.bws, "fir", True)["here"][0]["state"], "awake")

    def test_sounds_and_doings_show_up(self):
        self.bolt_at("fir")
        self.tick()
        self.plan("forage")
        self.tick()
        self.assertEqual(self.bolt.look(self.bws, "fir", True)["here"][0]["doing"], "foraging")
        self.plan("scold")
        self.tick()
        self.assertIn("Spike: a furious jay alarm call.", self.bolt.look(self.bws, "fir", True)["recent"])


class Things(Base):
    def test_gift_from_bolt_lands_once(self):
        self.tick()
        self.bolt_at("fir")
        self.bolt_does("give", to="spike", item="quartz crystal")
        self.tick()
        inv = self.spike.state["inv"]
        self.assertEqual(inv["quartz crystal from Bolt"]["kind"], "gift")
        self.assertEqual(self.bolt.look(self.bws, "fir", True)["deliveries"], [])
        self.restart_spike()                               # nothing shows up twice after a restart
        self.tick()
        self.assertEqual(self.spike.state["inv"]["quartz crystal from Bolt"]["count"], 1)

    def test_crash_before_the_ack_doesnt_double_it(self):
        self.tick()
        self.bolt_at("fir")
        self.bolt_does("give", to="spike", item="spoon")
        real_ack = self.spike.world.ack
        self.spike.world.ack = lambda ws: None             # the power goes out right after the save
        self.tick()
        self.spike.world.ack = real_ack
        self.restart_spike()
        self.tick()
        self.tick()
        self.assertEqual(self.spike.state["inv"]["spoon from Bolt"]["count"], 1)

    def test_he_gives_bolt_something(self):
        self.spike.inv_add(self.spike.state, "bottle cap", "shiny")
        self.spike.save()
        self.bolt_at("fir")
        self.tick()
        self.plan("give", "Bolt", "bottle cap")
        self.tick()
        self.assertNotIn("bottle cap", self.spike.state["inv"])
        got = self.bolt.look(self.bws, "fir", True)["deliveries"]
        self.assertEqual([(d["item"], d["from"]) for d in got], [("bottle cap", "Spike")])

    def test_a_refused_gift_comes_back(self):
        for i in range(4):
            self.spike.inv_add(self.spike.state, f"pebble {i}", "shiny")
        self.spike.save()
        self.bolt_at("fir")
        self.tick()
        for i in range(4):
            self.plan("give", "Bolt", f"pebble {i}")
            self.tick(minutes=6)
        self.assertIn("pebble 3", self.spike.state["inv"])            # the 4th of the day was refused
        self.assertEqual(len(self.bolt.look(self.bws, "fir", True)["deliveries"]), 3)

    def test_picks_up_what_bolt_dropped(self):
        self.bolt_at("fir")
        self.bolt_does("drop", item="spinner lure")
        self.tick()
        self.assertIn("LYING HERE: spinner lure", self.brain.prompts[-2])
        self.plan("pick_up", item="spinner lure")
        self.tick()
        self.tick()
        self.assertEqual(self.spike.state["inv"]["spinner lure"]["kind"], "shiny")

    def test_human_leave_goes_through_the_world(self):
        self.tick()
        m = {"id": "1", "author": {"id": "42", "username": "ellwood2150"}}
        self.spike.command(m, "Elliott", "!jay leave lake a red bobber")
        self.spike.world_settle()
        self.assertEqual(self.bolt_at("lake")["items"][0]["for"], "spike")
        self.plan("go", "lake")
        self.tick()
        self.tick()
        self.assertEqual(self.spike.state["inv"]["a red bobber from Elliott"]["kind"], "gift")


class Outages(Base):
    def test_world_away_he_lives_on(self):
        self.tick()
        self.down()
        for _ in range(3):
            start = time.time()
            self.tick()
            self.assertLess(time.time() - start, 3)
        self.assertIsNone(self.spike.state["world_view"])
        self.assertIn("world away", self.spike.status_text())
        acts = self.spike.actions(self.spike.state, self.spike.view(self.spike.state))
        self.assertFalse({"talk", "give", "pick_up"} & set(acts))
        self.up()
        self.tick()
        self.assertIn("world on", self.spike.status_text())

    def test_gift_sent_into_an_outage_arrives_once(self):
        self.spike.inv_add(self.spike.state, "bottle cap", "shiny")
        self.spike.save()
        self.bolt_at("fir")
        self.tick()
        self.plan("give", "Bolt", "bottle cap")
        real_send = self.spike.world.send
        self.spike.world.send = lambda ws: []              # the world goes away right after the save
        self.tick()
        self.spike.world.send = real_send
        self.assertEqual(len(self.spike.state["world"]["outbox"]), 1)
        self.down()
        self.restart_spike()
        self.tick()
        self.up()
        self.tick()
        self.tick()
        self.assertEqual(self.spike.state["world"]["outbox"], [])
        got = self.bolt.look(self.bws, "fir", True)["deliveries"]
        self.assertEqual([d["item"] for d in got], ["bottle cap"])


class AWeek(Base):
    def test_a_chaotic_week(self):
        """A week of chaos-brain life in the world with a busy Bolt and the world going away now and then.
        Every gift between them arrives exactly once, and nothing is left hanging."""
        rng = random.Random(7)
        self.spike = self.make_spike(brain=ChaosBrain(random.Random(3)))
        bolt_gave, places = [], ["fir", "lake", "creek", "junkyard"]
        for step in range(7 * 24 * 12 // 4):               # a tick every 20 minutes
            if rng.random() < 0.01 and self.server:
                self.down()
            elif not self.server and rng.random() < 0.2:
                self.up()
            if self.server and rng.random() < 0.3:
                self.bolt_at(rng.choice(places))
                r = rng.random()
                if r < 0.2:
                    item = f"bolt thing {step}"
                    for body, reply in self.bolt_does("give", to="spike", item=item):
                        if reply["ok"]:
                            bolt_gave.append(item)
                elif r < 0.5:
                    self.bolt_does("say", text="Caw, Spike!", to="spike")
            self.tick(minutes=20)
            if self.server and rng.random() < 0.5:
                self.spike.world_poll()
        if not self.server:
            self.up()
        self.clock.dt = self.clock.dt.replace(hour=11)
        for _ in range(3):
            self.tick()
        gifts = {n: it["count"] for n, it in self.spike.state["inv"].items() if n.endswith(" from Bolt")}
        for item in bolt_gave:
            self.assertEqual(gifts.get(f"{item} from Bolt"), 1, item)
        self.assertEqual(self.spike.state["world"].get("outbox", []), [])
        self.assertTrue(bolt_gave)


if __name__ == "__main__":
    unittest.main(verbosity=1)
