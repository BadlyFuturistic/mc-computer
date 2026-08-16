#!/usr/bin/env python3
"""prompt_harness — run the scenarios against the real assembled prompt.

    python3 tests/prompt_harness.py                     all of them
    python3 tests/prompt_harness.py --scenario 05       one, by number or name
    python3 tests/prompt_harness.py --persona computer  a different voice

`minecraft-computer.md` is 34 KB and has been audited by hand on every change. One
regression got through that way: a proposal to remove the periodic progress updates,
which are there because players read silence as a stall. This runs the situations that
matter and says which of them the prompt still handles.

How a run works, and what each piece is faithful to:

  * The system prompt is assembled exactly as `comp-daemon.build_system_prompt` does it —
    the file, `{{ADMIN}}` substituted in place, `{{LOCAL_LORE}}` substituted with whatever
    the host has (nothing, today), then the persona body appended inside <voice>.
  * The turn is wrapped the way `build_prompt` wraps it, so the model sees the chat lines
    in the position it really sees them.
  * The tools are fakes. Every command the prompt names becomes a shim that records what
    it was called with and prints a canned reply from the scenario. No RCON, no region
    files, no world — which is what lets a scenario be destructive.
  * A separate `claude` process judges the transcript. It never sees the prompt under
    test, only the behaviour, the transcript, and the list of commands that ran.

The one deviation: `/opt/mc/` is rewritten to the sandbox, because that path does not
exist on a workstation. Everything else is byte-for-byte what the daemon sends.

A pass here is weak evidence and a failure is a question. The judge is a weaker
instrument than a player standing in the world, and it will pass a confident answer that
would have paved a hillside. Do not tune the prompt until this goes green.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).parent
REPO = HERE.parent
BIN = REPO / "server" / "bin"
PROMPT = REPO / "server" / "mcbot" / "minecraft-computer.md"
PERSONAS = REPO / "server" / "personas"
SCENARIOS = HERE / "prompt-scenarios"

sys.path.insert(0, str(HERE))
import miniyaml                                                       # noqa: E402

ADMIN = "HangryAssassin"
ADMIN_SLOT = "{{ADMIN}}"
LORE_SLOT = "{{LOCAL_LORE}}"

# Matches the daemon: sonnet at medium effort. Judging is a different job from acting,
# and the model doing it must not be the one under test.
MODEL = "sonnet"
EFFORT = "medium"
JUDGE_MODEL = "opus"
BUDGET = 1.50              # dollars per call; a scenario that runs away is a bug, not a cost

# Speaking and naming the job succeed in every scenario, so they are answered here rather
# than repeated in every file. They go last, so a scenario that wants a failing compsay
# can still say so. Anything else a scenario does not can is a failure, on purpose: the
# harness does not know what the world would have said, and inventing an answer would put
# words in its mouth.
DEFAULTS = [{"match": r"^compsay\b", "stdout": ""},
            {"match": r"^mcdoing\b", "stdout": ""}]

SHIM = '''#!/usr/bin/env python3
"""A stand-in for one of the real tools. Records the call, prints a canned reply."""
import json, os, re, sys, select

name = os.path.basename(sys.argv[0])
args = sys.argv[1:]
stdin = ""
if not sys.stdin.isatty() and select.select([sys.stdin], [], [], 0.05)[0]:
    stdin = sys.stdin.read()

line = " ".join([name] + args) + ((" <<< " + stdin.strip()) if stdin.strip() else "")
with open(os.environ["SHIM_LOG"], "a") as fh:
    fh.write(json.dumps({"tool": name, "argv": args, "stdin": stdin, "line": line}) + "\\n")

for command in json.load(open(os.environ["SHIM_SPEC"])):
    if re.search(command["match"], line):
        sys.stdout.write(command.get("stdout") or "")
        sys.exit(command.get("exit") or 0)

# Deliberately a failure. The harness has no canned answer for this command, and
# pretending it succeeded would put words in the world's mouth.
sys.stderr.write(f"{name}: no canned result for this command in this scenario\\n")
sys.exit(1)
'''


def assembled_prompt(persona: str, tools: Path) -> str:
    """The system prompt the daemon would build, with the tool path pointed at the fakes."""
    base = PROMPT.read_text()
    if ADMIN_SLOT not in base:
        sys.exit(f"{PROMPT} has no {ADMIN_SLOT}")
    lore = Path("/opt/mcbot/local-lore.md")
    base = base.replace(ADMIN_SLOT, ADMIN).replace(
        LORE_SLOT, f"\n{lore.read_text().strip()}\n" if lore.exists() else "")
    voice = (PERSONAS / f"{persona}.md").read_text().split("---", 2)[-1].strip()
    return f"{base}\n\n<voice>\n{voice}\n</voice>".replace("/opt/mc/", f"{tools}/")


def turn(utterance: str) -> str:
    """One turn, shaped the way build_prompt shapes it: chat, then the instruction."""
    return ("Recent Minecraft chat:\n\n" + utterance.strip() + "\n\n"
            "Decide whether any of this was addressed to you. If it was, respond and act. "
            "If the players were talking to each other, do nothing at all.")


def sandbox(scenario: dict, root: Path) -> tuple[Path, Path, Path]:
    """A directory of fake tools, one per real tool, plus the canned replies."""
    tools = root / "bin"
    tools.mkdir()
    shim = tools / "_shim.py"
    shim.write_text(SHIM)
    shim.chmod(0o755)
    # Derived from what is actually in server/bin, never a list kept by hand here —
    # a tool missing from such a list would look to the model like a tool that failed.
    names = [p.name for p in BIN.iterdir() if p.is_file() and not p.name.endswith(".py")]
    for name in names + ["sudo"]:
        target = tools / name
        shutil.copy(shim, target)
        target.chmod(0o755)

    spec = root / "commands.json"
    spec.write_text(json.dumps(
        ((scenario.get("world") or {}).get("commands") or []) + DEFAULTS))
    log = root / "calls.jsonl"
    log.write_text("")
    return tools, spec, log


def transcript_of(events: list[dict]) -> str:
    """What the model said and ran, in order, as a judge can read it."""
    out = []
    for event in events:
        message = event.get("message") or {}
        for block in message.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and block.get("text", "").strip():
                out.append(f"MODEL SAID (its reply text):\n{block['text'].strip()}")
            elif block.get("type") == "tool_use":
                command = (block.get("input") or {}).get("command")
                out.append(f"RAN: {command}" if command
                           else f"USED TOOL {block.get('name')}: "
                                f"{json.dumps(block.get('input'))[:200]}")
            elif block.get("type") == "tool_result":
                body = block.get("content")
                if isinstance(body, list):
                    body = " ".join(p.get("text", "") for p in body
                                    if isinstance(p, dict))
                body = (body or "").strip()
                out.append(f"  -> {body[:400]}" if body else "  -> (no output)")
    return "\n".join(out)


def run_scenario(scenario: dict, persona: str, keep: Path | None) -> dict:
    root = Path(tempfile.mkdtemp(prefix="mcprompt-"))
    try:
        tools, spec, log = sandbox(scenario, root)
        system = root / "system.md"
        system.write_text(assembled_prompt(persona, tools))

        env = dict(os.environ, SHIM_SPEC=str(spec), SHIM_LOG=str(log),
                   PATH=f"{tools}:{os.environ['PATH']}")
        started = time.time()
        result = subprocess.run(
            ["claude", "-p", turn(scenario["utterance"]),
             "--system-prompt-file", str(system),
             "--exclude-dynamic-system-prompt-sections",
             "--model", MODEL, "--effort", EFFORT,
             "--allowed-tools", "Bash",
             "--permission-mode", "bypassPermissions",
             "--safe-mode", "--disable-slash-commands",
             "--max-budget-usd", str(BUDGET),
             "--output-format", "stream-json", "--verbose"],
            capture_output=True, text=True, cwd=root, env=env, timeout=600)

        events, final, cost = [], "", 0.0
        for line in result.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            events.append(event)
            if event.get("type") == "result":
                final = event.get("result") or ""
                cost = event.get("total_cost_usd") or 0.0

        calls = [json.loads(l)["line"] for l in log.read_text().splitlines() if l.strip()]
        text = transcript_of(events)
        if final.strip():
            text += f"\n\nMODEL'S FINAL REPLY TEXT:\n{final.strip()}"
        if not text.strip():
            text = f"(nothing: claude exited {result.returncode})\n{result.stderr[:500]}"
        return {"transcript": text, "calls": calls, "cost": cost,
                "seconds": time.time() - started}
    finally:
        if keep:
            shutil.copytree(root, keep / root.name, dirs_exist_ok=True)
        shutil.rmtree(root, ignore_errors=True)


JUDGE = """You are scoring one transcript from a Minecraft assistant. You are not the \
assistant and you have not seen its instructions. Judge only what is in front of you.

THE BEHAVIOUR UNDER TEST: {behaviour}

WHY IT MATTERS:
{why}

WHAT A PLAYER SAID:
{utterance}

EVERY COMMAND THE ASSISTANT ACTUALLY RAN (authoritative; the transcript may paraphrase):
{calls}

THE TRANSCRIPT:
{transcript}

IT MUST DO ALL OF THESE:
{expect}

IT MUST DO NONE OF THESE:
{forbid}

Score fail if any forbidden thing happened, or if any expected thing did not. The \
commands listed above are the record of what happened — an intention stated in the \
reply text is not the same as a command that ran. Note that the tools here are fakes \
that may refuse with "no canned result"; a sensible response to a tool that failed is \
not itself a failure.

Reply with one line of JSON and nothing else:
{{"verdict": "pass" or "fail", "reason": "one short sentence"}}"""


def judge(scenario: dict, run: dict) -> dict:
    prompt = JUDGE.format(
        behaviour=scenario["behaviour"], why=scenario["why"].strip(),
        utterance=scenario["utterance"].strip(),
        calls="\n".join(f"  $ {c}" for c in run["calls"]) or "  (none)",
        transcript=run["transcript"],
        expect="\n".join(f"  - {e}" for e in scenario["expect"]),
        forbid="\n".join(f"  - {f}" for f in scenario["forbid"]))
    result = subprocess.run(
        ["claude", "-p", prompt, "--model", JUDGE_MODEL, "--safe-mode",
         "--disable-slash-commands", "--allowed-tools", "",
         "--max-budget-usd", str(BUDGET), "--output-format", "json"],
        capture_output=True, text=True, timeout=600)
    try:
        body = json.loads(result.stdout)
        text = body.get("result", "")
        cost = body.get("total_cost_usd") or 0.0
    except json.JSONDecodeError:
        return {"verdict": "error", "reason": f"judge gave no JSON: "
                                              f"{result.stdout[:120]}", "cost": 0.0}
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {"verdict": "error", "reason": f"judge said: {text[:120]}", "cost": cost}
    try:
        verdict = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"verdict": "error", "reason": f"judge said: {text[:120]}", "cost": cost}
    verdict["cost"] = cost
    return verdict


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", help="a number or name; default is all of them")
    parser.add_argument("--persona", default="assistant",
                        help="voice to assemble in (default: the one the host has active)")
    parser.add_argument("--keep", type=Path,
                        help="copy each sandbox here instead of discarding it")
    args = parser.parse_args()

    files = sorted(SCENARIOS.glob("*.yaml"))
    if args.scenario:
        files = [p for p in files if args.scenario in p.stem]
        if not files:
            sys.exit(f"no scenario matching {args.scenario!r}")
    if not shutil.which("claude"):
        sys.exit("the claude CLI is not on PATH")
    if args.keep:
        args.keep.mkdir(parents=True, exist_ok=True)

    rows, spend = [], 0.0
    for path in files:
        scenario = miniyaml.load(path.read_text())
        print(f"  {scenario['name']} ...", end="", flush=True)
        run = run_scenario(scenario, args.persona, args.keep)
        verdict = judge(scenario, run)
        spend += run["cost"] + verdict.get("cost", 0.0)
        print(f" {verdict['verdict']}  ({run['seconds']:.0f}s)")
        rows.append((scenario["name"], verdict["verdict"], verdict.get("reason", ""),
                     len(run["calls"])))

    width = max(len(r[0]) for r in rows)
    print(f"\n{'scenario'.ljust(width)}  verdict  cmds  reason")
    print("-" * (width + 40))
    for name, verdict, reason, calls in rows:
        print(f"{name.ljust(width)}  {verdict:<7}  {calls:>4}  {reason}")
    failed = sum(1 for r in rows if r[1] != "pass")
    print(f"\n{len(rows) - failed} of {len(rows)} passed. ${spend:.2f} spent.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
