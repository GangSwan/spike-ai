# The jay

A young Steller's jay living in Bolt's town under Mount Shasta. Nobody gives him tasks.
Every 5 minutes of daylight he looks around, checks his energy and mood, and decides what
to do. He sleeps at night (no model calls). He names himself on his first morning.

- **Brain:** OpenAI `gpt-5-nano`, 2 short calls per waking tick. Roughly $1–2/month, with
  a hard daily cap (`daily_budget_usd`, default $0.25).
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
  - Also: watch, think, nap, eat, reminisce.
- **Painting (his own skill):** once a day at dusk, and whenever someone asks, he paints a real
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
  - Per-person facts.
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

## Discord commands

| Command | Who | Does |
|---|---|---|
| `!jay give <thing>` | anyone | gives him a gift (gifts are never eaten, cached or given away) |
| `!jay leave <place> <thing>` | anyone | hides something; he finds it when he flies there |
| `!jay paint <anything>` | anyone | asks him to paint something (max 6 a day; at night he paints it in the morning) |
| `!jay status` | anyone | place, energy, mood, skills, today's spend |
| `!jay pause` / `!jay resume` | owner | freezes / unfreezes him |

You can also name him the way Bolt's commands work: `!give spike <thing>`, `!leave spike <place> <thing>`,
`!paint spike <anything>`, `!status spike`, and owner-only `!stop spike` / `!start spike`.

He also answers anyone who says his name or replies to one of his messages.
`!give`, `!leave` and `!call` without `jay` are Bolt's commands, and he ignores them.

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
