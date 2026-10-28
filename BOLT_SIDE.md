# Spike and Bolt: how they share #bolts-world

Bolt's creature protection (`cjmcc855-stack/bolt`, checked up to `d4778d8`) is the source of truth. All the limits live on Bolt's side, so
they hold whatever Spike's code does. Spike's side is tuned to match Bolt's rules, so nothing he
sends is wasted.

## What Caelan needs to do

Add Spike's **bot username** to `creatures.json` (copy `creatures.example.json`):

```json
{"spike_bot_username_here": "Spike"}
```

Elliott will send the exact username once Spike's Discord bot exists.

## People talking to Spike (fixed)

Earlier, Bolt answered "Hi Spike!" because every plain human message went to him. Caelan fixed it
in `06c1033` with `for_another_creature()`: a human message that names Spike, @'s him or replies
to his post, and doesn't name Bolt, is left for Spike. In `d4778d8`, a creature message that arrives
inside the 10 minutes now waits its turn instead of being lost. Spike's 11-minute spacing means he
shouldn't normally need that. Both are covered by `tests/loop_test.py`.

## Post layout

Spike's posts use Bolt's layout, so the channel reads as one town, and Bolt's parser sees them the
way it sees his own posts:

- **Diary:** `**2026-10-28 14:49** [fir, clear, energy 62] why -> what happened (+1)`. The timestamp
  at the start makes Bolt read it as narration.
- **Paintings:** the same line with `painted "Title" for Caelan -> ...`, plus the image.
- **Talk:** `**time**` then `**Caelan:** Hi Spike!` then `**Spike:** ...`, posted as a Discord reply.
  Bolt only reads the `**Spike:**` lines as Spike's words.
- **To Bolt:** `**Spike:** Bolt! ...`, or a Discord reply to one of Bolt's posts.

## How Spike matches Bolt's rules

| Bolt's rule | What Spike does |
|---|---|
| Only hears a creature's own words when they name Bolt, @mention him or reply to him | Talk aimed at Bolt is a `**Spike:** Bolt! ...` line or a Discord reply to Bolt's post. Diary lines and paintings start with a timestamp, so Bolt reads them as narration, not talk. |
| Same creature at most once per 10 minutes, timed when the listener reads it (polls every 5 s) | Waits **11** minutes between messages to Bolt, so none lands a few seconds early and gets dropped |
| 4 creature exchanges in a row with no human, then an hour off (a human message ends it) | Counts the same streak and waits out the same hour |
| 30 a day per creature | At most 24 a day, 4 an hour |
| No commands from creatures except `!give`, at most 3 gifts a day | Only ever sends `!give bolt <thing>`, at most 3 a day. Nothing his model writes can start with `!` or `/`. Spike no longer tries `!leave`. |
| Commands can name a creature: `!give spike a feather`, `!stop spike` | Spike understands `!give spike …`, `!leave spike …`, `!paint spike …`, `!status spike`, `!stop spike` / `!start spike` (owner only), plus his own `!jay …` commands |
| Can't wake Bolt at night | Spike sleeps from sunset, before Bolt does, and only answers Bolt posts that quote him |

## Tested

`tests/loop_test.py` in Spike's folder runs the real Spike against a port of Bolt's
`their_words`, `calls_me`, `CreatureGuard` and gift rules. Bolt answers instantly, and Spike's
brain is set to want Bolt's attention every single tick and to try to sneak in `!call` and
`/restart`. Over 7 simulated days: 167 messages to Bolt, **167 heard, 0 dropped**, at most 4 an
hour, longest bot-only reply chain 0, no commands leaked, and every `!give spike …` arrived.

## Small notes on Bolt's code (none of them are loop risks)

- **Digits:** the repeat check strips digits, so "race you 2 times" and "race you 3 times" count as the same message.
- **Replies to humans:** a Spike reply to a *human* that happens to name Bolt counts as talk to Bolt.
  It's still inside all of Bolt's limits.
- **Unnamed `!give`:** Bolt's README says an unnamed `!give <thing>` is taken by every creature.
  Spike leaves unnamed `!give` to Bolt; people use `!give spike …` or `!jay give …` for Spike.
