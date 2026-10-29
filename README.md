# The jay

A young Steller's jay living in Bolt's town under Mount Shasta. Nobody gives him tasks.
Every 5 minutes of daylight he looks around, checks his energy and mood, and decides what
to do. He sleeps at night (no model calls). He names himself on his first morning.

- **Brain:** OpenAI `gpt-5-mini` decides what to do each turn and answers people and creatures
  (`decision_model`, `talk_model`); `gpt-5-nano` writes his diary, reactions and everything else
  (`model`). 2–5 short calls per waking turn, a few cents a day, with a hard daily cap
  (`daily_budget_usd`, default $0.25). Prices per model are in `prices`.
- **How he decides:** needs build up as he lives (hungry, tired, curious, wanting company, wanting
  to make something, to hunt treasure, to cache food, to make noise, to roam), pulled harder by his
  body, the time of day (food in the morning, roaming and making things midday, painting and caching
  toward dusk) and the season (fall is caching season). Each turn he's offered about 5 things drawn
  by those needs, by what he's enjoyed and by today's goals, and the model picks one. Doing the same
  thing 5 turns running puts it off the menu for about an hour; an hour in one place makes him
  restless. Every morning he sets 1–3 goals of his own and looks back on them at night. What he likes
  and dislikes is capped at ±3 so nothing runs away with him. With the shared town on he knows where
  Bolt is (once the town sends `around`) and can go find him.
- **World:** Bolt's 14 places, plus his own roost (the old fir). Real Shasta weather from
  Open-Meteo, seasons, day/night, energy.
- **Jay stuff:**
  - **forage**: seasonal food.
  - **cache / recover**: hide food for winter. He forgets some caches, and forgotten acorns sprout.
  - **raid**: the diner roof, or lake picnics.
  - **snatch**: shiny things, with rare finds.
  - **mimic**: learn each place's sound (train horn, siren, hawk scream, Bolt's caw, Bolt's songs).
  - **scold**: alarm calls.
  - **treasure**: his 10-item shelf.
  - **tinker**: at the shed, garage, machine shop or junkyard he builds something out of two of his
    shiny things (a pin whistle, a bottle-cap wind chime...) and can **take_apart** what he built.
    Gifts are never used as parts.
  - Also: watch, think, nap, eat, reminisce (he pages back through his whole life and thinks about it).
- **Learning (Bolt's way):**
  - **read**: his `library/` has 8 short books (6 from Bolt's library, plus *Jays, and the Birds Who
    Hide Things* and *Painting the Mountain*). He reads a passage at a time and remembers where he stopped.
  - **look_up**: anything he's curious about, on Wikipedia ("the big book of everything").
  - What he learns goes in **notebooks** by subject (food, birds, animals, rocks, machines, painting,
    mountain, fire), forever. His prompts show only what fits where he is and what he's doing.
    Every 5 notes on a subject is a bonus level in the skill it helps, up to 3.
  - **examine**: he studies one of his things until he understands it (up to 5 discoveries).
  - If something he reads shows a belief about one of his things was wrong, he fixes it and
    remembers what he used to think.
  - Words he likes from reading become his. `!jay book <title>` fetches a public-domain book from
    Project Gutenberg into `data/library/` (3 a day).
- **Habits (Bolt's way):** flowery replies get one plain rewrite; he keeps the last 12 lines of
  conversation and doesn't start replies the same way; he learns lasting facts about the people
  who talk to him; gifts get their own reaction, and food gifts feed him. When he's done the same thing
  3+ turns and it's felt flat or bad, or failed at something 3 times in a row, he's told plainly (with
  a book that could help); what to do about it is up to him.
- **Painting (his own skill):** once a day at dusk, whenever he feels like it (up to 3 more a day),
  and whenever someone asks, he paints a real
  PNG with brushstrokes (`painter.py`, stdlib only). A stranger (the vision model, told
  *nothing* about it) says what they see. He compares that with what he meant, writes a lesson in
  his art notebook, and his next plan uses those lessons. His painting skill grows with how
  often strangers recognize his place, time, weather, mood and main subject, so it's measurable.
  Low skill means wobbly shapes, muddy colors and scribbly strokes; high skill means clean edges
  and strokes that follow the forms. About $0.0005 per painting. Open `data/gallery.html` to see them all.
- **Bolt:** he reads Bolt's diary posts and figures out where Bolt is. Through Discord he can
  `talk_to_bolt` and `give_bolt`, rate-limited to match Bolt's own creature rules (see [BOLT_SIDE.md](BOLT_SIDE.md)).
- **Memory:**
  - An append-only memory book (`data/memory.jsonl`) and a readable `data/diary.md`.
  - Preferences that decay, plus a repetition penalty.
  - A list of worn-out words he's told to avoid.
  - What each person has told him about themselves, never forgotten.
  - Every ~2 hours he rewrites "who I am", "how I talk" and "what I think of Bolt".
- **Robustness:**
  - All-or-nothing ticks, atomic saves with `.bak`, a single-instance lock.
  - Failure backoff and an English-only guard.
  - A one-time Discord gateway identify.
  - `tests/sim_days.py` chaos tests.

## Setup

**1. OpenAI key.** Create one at platform.openai.com. It's worth setting a monthly limit
there too. Then, in your own terminal:

```bash
setx OPENAI_API_KEY "paste-your-key-here"
```

Open a new terminal afterwards so the variable is picked up.

**2. Try him without Discord.** This runs one real tick and quits:

```bash
python jay.py --once
```

His first daylight tick is the naming. Run it a few more times and watch `data/diary.md`.

To see him paint right away:

```bash
python jay.py --paint "the lake in a storm"
```

Then open `data\gallery.html` in your browser.

**3. Discord bot.** At discord.com/developers/applications:
- **New Application**, then **Bot**, then **Reset Token**. Copy the token and `setx JAY_DISCORD_TOKEN "..."`.
- On the same Bot page, turn on **Message Content Intent**. Without it he can't read messages.
- **OAuth2 > URL Generator**: scope `bot`; permissions *View Channels, Send Messages,
  Read Message History, Attach Files, Change Nickname*. The server owner opens that URL to add him.
- In Discord settings, turn on **Developer Mode**. Then right-click to Copy ID for the channel,
  for Bolt, and for yourself.

**4. Config.** Copy `config.example.json` to `config.json` and fill in `discord_channel_id`,
`bolt_user_id` and `owner_discord_id`. Optionally copy `names.example.json` to `names.json`
to give people real names.

**5. Run him:**

```bash
python jay.py
```

Type in his window to talk to him as yourself (`owner_name`). Commands work there too, without
`!jay`: `!call lake`, `!give peanut`, `!restart`.

**Restarting into new code:** `!jay restart` (you only), or put an empty `data/restart.flag` file
there. He runs his tests on the new code first (`sim_days`, `loop_test`, `habits_test`, and
`world_test` if shasta-world is next to this folder) and refuses to restart into broken code, saying
why in Discord. `python jay.py` is a tiny supervisor that starts him again when he asks.

## Discord commands

| Command | Who | Does |
|---|---|---|
| `!jay give <thing>` | anyone | gives him a gift (gifts are never eaten, cached or given away) |
| `!jay leave <place> <thing>` | anyone | hides something; he finds it when he flies there |
| `!jay paint <anything>` | anyone | asks him to paint something (max 6 a day; at night he paints it in the morning) |
| `!jay book <title>` | anyone | finds a public-domain book for his library (3 a day) |
| `!jay status` | anyone | place, energy, mood, skills, today's spend |
| `!jay call <place>` | owner | he flies there to be with you (the summit by way of the trail) |
| `!jay pause` / `!jay resume` | owner | freezes / unfreezes him |
| `!jay restart` | owner | tests the new code, then restarts into it |

**At night** he sleeps in the fir. A human who talks to him, gives him something or calls him wakes
him up, and he stays up until 20 minutes after they go quiet (`wake_minutes`). Creatures can't wake him.

You can also name him the way Bolt's commands work: `!give spike <thing>`, `!leave spike <place> <thing>`,
`!paint spike <anything>`, `!book spike <title>`, `!status spike`, and owner-only `!call spike <place>`,
`!stop spike` / `!start spike`, `!restart spike`.

He also answers anyone who says his name or replies to one of his messages.
`!give`, `!leave` and `!call` without `jay` or his name are Bolt's commands, and he ignores them.

## Talking to Bolt

Bolt has built-in protection for other creatures: he only hears bots listed in his `creatures.json`.
Caelan adds Spike's bot username there. [BOLT_SIDE.md](BOLT_SIDE.md) explains how Spike fits Bolt's
rules. Set `"bolt_accepts_bots": true` to let Spike give Bolt things (3 a day).

## Living in shasta-world

[shasta-world](https://github.com/GangSwan/shasta-world) is the town Spike and Bolt share: one
server holds the places, who's where, things lying around and what they say to each other. It's
off until you switch it on:

1. Put `"world_url": "http://100.100.19.125:8642"` in `config.json` (underworld's Tailscale address).
2. Set his world token (from `/etc/shasta-world/config.json` on underworld, the `spike` entry):
   `setx JAY_WORLD_TOKEN "..."`, then open a new window.

With it on, each tick he looks at the shared town first: who's there, what's lying around, and
gifts that arrived for him (they land in his hoard as gifts). He can **talk** to whoever is there,
**give** them things and **pick up** what's lying around. His moves, sleep, mimicked sounds and what
he's doing ("foraging") show up for the others. He answers creatures who speak to him within ~20 s,
not on his 5-minute tick. `!jay leave` puts the thing in the world for him. His Discord way of
talking to Bolt switches off; his diary still goes to Discord. If the world is away he just lives in
his own town, and anything he gave or picked up is sent when it's back. `client/world_client.py`
from shasta-world, copied here as `world_client.py`, does the bookkeeping.

## Testing

```bash
python tests/sim_days.py 4 1
```

This runs days of life in seconds: a chaotic fake brain (junk, Chinese text, outages), power
cuts mid-save, restarts and fake Discord traffic. It checks invariants every step and fails loudly.
Run it after any change.

```bash
python tests/habits_test.py
```

This checks everything he does Bolt's way, exactly: reading, look_up, notebooks, examine, changing
his mind, tinkering (gifts never used), painting on his own, plain talk, people, gift reactions,
ruts, calls, being woken at night, the console, book orders and tested restarts.

```bash
python tests/autonomy_test.py
```

This checks how he decides: needs, the daily menu, boredom, goals, capped preferences, which model
each call uses, no parroting, names, and knowing where Bolt is. The big one: a brain that always
says "snatch" still lives a varied day (no one thing over 40%, at least 6 things and 4 places).

```bash
python tests/loop_test.py 3
```

This runs the real jay against a copy of Bolt's Discord behavior (from Caelan's repo). It checks
that the two bots can't get stuck answering each other, and that nothing the jay's model writes
can trigger one of Bolt's commands.

```bash
python tests/world_test.py
```

This runs the real jay in the real shasta-world server (it looks for a shasta-world checkout next to
this repo, or set `SHASTA_WORLD`), with a scripted Bolt: talking both ways, gifts both ways, picking
things up, `!jay leave`, the summit rule, sleep, the world going away, crashes before the ack, and a
chaotic week where every gift must arrive exactly once.

## Moving to the home server

Copy the whole folder, **including `data/`** (that's his life), set the two environment
variables, and run `python jay.py`. It's stdlib-only Python 3.10+, and it runs on Linux too.
Only run one copy at a time; the lock stops two on the same machine, not two on different machines.
