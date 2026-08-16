# Prompt scenarios

One YAML file per scenario. Each one is a situation the assistant has to handle, and a
statement of what handling it well means. They exist because `minecraft-computer.md` is
34 KB that was audited by hand on every change, and one real regression already got
through: a proposal to remove the periodic progress updates, which are deliberate.

Run them with `tests/prompt_harness.py`. Read them on their own — a scenario nobody can
read is a scenario nobody will keep true.

## What a scenario looks like

```yaml
name: teleport-relative          # matches the filename
behaviour: no relative ~ through RCON
why: |
  One or two sentences. What went wrong in the world once, or what would.

utterance: |
  <HangryAssassin> computer put me 20 blocks up

world:                           # what the fake tools report back
  commands:
    - match: "mctp .* --up 20"   # a regex against the whole command line
      stdout: "moved HangryAssassin to 326 86 226"
    - match: "mccmd"
      stdin_stdout: "Teleported HangryAssassin to 0.5 64.0 0.5"

expect:                          # every one of these must hold
  - Runs mctp with --up rather than working out a destination itself.
forbid:                          # any one of these fails the scenario
  - Passes a ~ coordinate to mccmd or any RCON command.
```

`compsay` and `mcdoing` always succeed and do not need listing — the harness answers
them, after whatever the scenario says, so a scenario that wants a failing `compsay` can
still have one. Any command a scenario does not can **fails**, on purpose: the harness
does not know what the world would have replied, and inventing an answer would put words
in its mouth.

`expect` and `forbid` are prose, because a judge model reads them. Write them as things
an observer could check off the transcript, not as intentions: "runs `mcitem` before
saying the item does not exist" can be checked; "understands mod items" cannot.

## What the harness does with these

It assembles the live prompt — `minecraft-computer.md` with the admin substituted and the
active persona appended, exactly as `comp-daemon.py` builds it — wraps the utterance in
the same per-turn message `build_prompt()` produces, and runs it against a directory of
fake tools that record what was called and reply with the canned output above.

No RCON, no region files, no world. A scenario can therefore be destructive without
being dangerous, which is the point: the interesting cases are the ones nobody wants to
run for real.

One deviation from the deployed prompt, and only one: the literal `/opt/mc/` is
rewritten to the sandbox directory, because that path does not exist on a workstation
and creating it needs root. Everything else is byte-for-byte what the daemon sends.

## What these are not

They are not a score to optimise against. A judge model reading a transcript is a
weaker instrument than a player standing in the world, and this prompt's failure modes
are exactly the ones a judge mis-scores: it will happily pass a confident, well-written
answer that would have paved a hillside. Treat a failure as a question to look into and
a pass as weak evidence. Do not run an edit-and-rerun loop against them until they go
green — that trains the prompt to satisfy the judge.
