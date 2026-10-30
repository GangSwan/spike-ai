#!/usr/bin/env python3
"""
Spike takes up graffiti: spray paint, walls, and pieces going up in shasta-world (PROTOCOL.md section 10).
The real server (from a shasta-world checkout) in test mode, the real Spike with a scripted brain, and a
scripted Bolt, the same way tests/world_test.py does it.

    python tests/graffiti_test.py
"""

import json
import random
import struct
import sys
import unittest
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import world_test as W  # noqa: E402  (finds shasta-world, or says how to)
import painter  # noqa: E402

J = W.J


class SprayBrain(W.ScriptBrain):
    """Designs every piece the same way, and otherwise does what the test lines up."""

    def __init__(self):
        super().__init__()
        self.designs = 0

    def ask(self, system, user, max_tokens=1200, image_b64=None, **kw):
        if '"words"' in user:
            self.designs += 1
            self.prompts.append(user)
            return {"words": "RING DAY", "colors": ["#ff4fa0", "#ffd23f", "#2ec4f0"], "title": "Ring Day",
                    "picture": "jay", "tag_name": "Spk!", "feeling": 2}, 0.0
        return super().ask(system, user, max_tokens, image_b64, **kw)


class Base(W.Base):
    def setUp(self):
        super().setUp()
        self.brain = SprayBrain()
        self.spike = self.make_spike()

    def at(self, place, paint=3, paint_level=0):
        st = self.spike.state
        st["place"], st["graffiti"]["paint"] = place, paint
        st["skills"]["paint"] = {0: 0, 3: 60, 6: 250}.get(paint_level, 0)
        self.spike.save()
        self.tick()

    def acts(self):
        return self.spike.actions(self.spike.state, self.spike.view(self.spike.state))

    def marks(self, place):
        with urllib.request.urlopen(f"{self.url}/v1/marks?place={place}", timeout=5) as r:
            return {w["surface"]: w["pieces"] for w in json.loads(r.read())["walls"]}

    def town_map(self):
        with urllib.request.urlopen(f"{self.url}/v1/map", timeout=5) as r:
            return json.loads(r.read())


class Pictures(unittest.TestCase):
    def test_every_kind_makes_a_picture_the_world_takes(self):
        for kind in painter.KINDS:
            for material in painter.MATERIALS:
                plan = painter.normalize_graffiti({"words": "spike & bolt!!", "colors": ["#123456"]}, kind, material,
                                                  "rail_yard", "spk")
                png = painter.make_graffiti(plan, 5, 7)
                self.assertTrue(painter.png_ok(png), (kind, material))
                self.assertLess(len(png), 256 * 1024)
                self.assertEqual(struct.unpack(">II", png[16:24]), (400, 300))

    def test_words_fit_the_font(self):
        self.assertEqual(painter.graffiti_words("hi, Bolt! :)"), "HI BOLT!")
        self.assertEqual(painter.graffiti_words("ñ✨"), "")
        plan = painter.normalize_graffiti({"words": "✨"}, "nonsense", "marble", "lake", "")
        self.assertEqual((plan["kind"], plan["material"], plan["words"], plan["tag_name"]), ("tag", "concrete", "SPK", "SPK"))


class Paint(Base):
    def test_spray_paint_turns_up_where_people_fix_and_junk_things(self):
        st = self.spike.state
        st["place"] = "junkyard"
        self.spike.rng = random.Random(3)
        found = 0
        for _ in range(40):
            text, special, _ = self.spike._do_snatch(st, {"target": "", "item": "", "why": ""}, None)
            found += "spray paint" in text or "paint marker" in text
        self.assertGreater(found, 0)
        self.assertLessEqual(st["graffiti"]["paint"], 2 * J.CAN_PIECES + J.CAN_PIECES)
        self.assertIn("spray paint: enough for", self.spike.inv_summary(st))

    def test_no_paint_or_no_world_means_no_tagging(self):
        self.at("rail_yard", paint=0)
        self.assertNotIn("tag", self.acts())
        self.spike.state["graffiti"]["paint"] = 2
        self.assertIn("tag", self.acts())
        self.assertIn("the water tower (bare)", self.acts()["tag"])
        self.spike.state["place"] = "summit"            # no walls up there
        self.assertNotIn("tag", self.acts())


class Pieces(Base):
    def test_a_piece_goes_up_on_the_wall(self):
        self.at("rail_yard", paint=2)
        self.bolt_at("rail_yard")
        self.plan("tag", "the water tower")
        self.tick()
        spike = next(c for c in self.town_map()["creatures"] if c["id"] == "spike")
        self.assertEqual(spike["tagging"]["surface"], "water_tower")      # the map's "tagging now"
        self.assertEqual(self.spike.state["graffiti"]["paint"], 1)
        self.assertIn("sprayed #1", self.spike.spray_next())
        g = self.spike.state["graffiti"]
        self.assertEqual(g["tag_name"], "SPK!")
        [piece] = g["pieces"]
        self.assertTrue((self.spike.dir / "graffiti" / piece["file"]).exists())
        [up] = self.marks("rail_yard")["water_tower"]
        self.assertEqual((up["id"], up["by"], up["kind"]), (piece["mark"], "Spike", "tag"))
        seen = self.bolt.look(self.bws, "rail_yard", True)
        self.assertEqual(seen["walls"][0]["by_name"], "Spike")
        self.assertIn("Spike painted something new on the water tower.", seen["recent"])
        self.assertEqual(self.spike.state["world"]["outbox"], [])
        post = self.spike.state["outbox"][-1]
        self.assertIn("sprayed a tag on the water tower", post["text"])
        self.assertTrue(post["file"].endswith(piece["file"]))
        self.assertIn("sprayed a tag", self.spike.memories[-1]["text"])
        self.assertEqual(self.spike.state["tag_queue"], [])

    def test_better_painters_do_throwups_and_murals(self):
        self.at("old_barn", paint=6, paint_level=6)
        kinds = set()
        for wall in ("barn door", "silo", "barn door", "silo"):
            self.spike.state["graffiti"]["days"] = {}
            self.plan("tag", wall)
            self.tick()
            self.spike.spray_next()
            kinds.add(self.spike.state["graffiti"]["pieces"][-1]["kind"])
        self.assertTrue(kinds & {"throwup", "mural"}, kinds)

    def test_he_paints_over_his_own_piece_but_not_bolts(self):
        self.at("garage", paint=3)
        self.plan("tag", "roll-up door")
        self.tick()
        self.spike.spray_next()
        first = self.spike.state["graffiti"]["pieces"][-1]["mark"]
        self.bolt_at("garage")
        req = urllib.request.Request(f"{self.url}/v1/marks/b1?place=garage&surface=back_wall&kind=tag", method="PUT",
                                     data=painter.make_graffiti(painter.normalize_graffiti({}, "tag", "brick", "garage", "BLT"), 3, 1))
        req.add_header("Authorization", "Bearer test-bolt")
        urllib.request.urlopen(req, timeout=5).read()
        self.tick()
        menu = self.acts()["tag"]
        self.assertIn("the roll-up door (your own piece is on it)", menu)
        self.assertNotIn("back wall", menu)
        self.plan("tag", "back wall")                    # he can't: it goes on his own wall instead
        self.tick()
        self.spike.spray_next()
        last = self.spike.state["graffiti"]["pieces"][-1]
        self.assertEqual(last["surface"], "roll_door")
        roll = self.marks("garage")["roll_door"]
        self.assertEqual([p["id"] for p in roll], [last["mark"], first])
        self.assertEqual(roll[0]["over"], first)

    def test_a_refused_piece_is_remembered_as_not_up(self):
        self.at("shed", paint=2)
        self.plan("tag", "shed door")
        self.tick()
        # Bolt gets there first, between Spike starting and his picture arriving
        req = urllib.request.Request(f"{self.url}/v1/marks/b2?place=shed&surface=door&kind=tag", method="PUT",
                                     data=painter.make_graffiti(painter.normalize_graffiti({}, "tag", "wood", "shed", "BLT"), 3, 2))
        req.add_header("Authorization", "Bearer test-bolt")
        urllib.request.urlopen(req, timeout=5).read()
        self.spike.spray_next()
        piece = self.spike.state["graffiti"]["pieces"][-1]
        self.assertFalse(piece["up"])
        self.assertTrue(any("didn't go up" in e for e in self.spike.state["events"]))

    def test_painted_while_the_world_is_away_goes_up_once_it_is_back(self):
        self.at("junkyard", paint=2)
        self.plan("tag", "gate")
        self.tick()
        self.down()
        self.spike.spray_next()
        self.assertEqual(len(self.spike.state["world"]["outbox"]), 1)
        self.restart_spike()                             # and a power cut, for good measure
        self.up()
        self.tick()
        self.tick()
        self.assertEqual(self.spike.state["world"]["outbox"], [])
        self.assertEqual(len(self.marks("junkyard")["gate"]), 1)

    def test_three_pieces_a_day(self):
        self.at("rail_yard", paint=9)
        for wall in ("water tower", "boxcar", "signal shed"):
            self.plan("tag", wall)
            self.tick()
            self.spike.spray_next()
        self.assertNotIn("tag", self.acts())
        self.clock.dt = self.clock.dt.replace(day=self.clock.dt.day + 1)
        self.assertIn("tag", self.acts())


if __name__ == "__main__":
    unittest.main(verbosity=1)
