# Conjure3D — Resuming after a break

For future-you (or anyone) returning to this project after time away. Read this first, then [HANDOFF.md](HANDOFF.md) for deeper architectural context.

## What this project is in one sentence

Conjure3D is a Windows desktop app: text description → sliceable 3D-print file. Tauri 2 + React + Python sidecar + Blender via MCP socket + Bambu Studio launch handoff. Build progress is tracked across 30 issues in 9 phases per [ISSUES.md](ISSUES.md).

## Where work happens

| | |
|---|---|
| Active worktree | `C:\Users\Business\Desktop\Project's\Conjure3D\.claude\worktrees\sad-bartik-e11c5a` |
| Active branch | `claude/sad-bartik-e11c5a` |
| Build identifier | `com.conjure3d.desktop` |
| Commit identity (per-command) | `git -c user.name=Conjure3D -c user.email=spmpermanent@gmail.com` |

The path contains an apostrophe (`Project's\`). That's deliberate — it forces every tool we touch to handle apostrophe paths correctly. We have a vendored patch of `tauri-winres` at `src-tauri/vendor/tauri-winres/` for this; don't remove it.

## How to figure out where you left off — in order

Spend two minutes on these and you'll know exactly what's next:

1. **`git log --oneline -10`** — the most recent commit's message starts with `Phase X Issue #N`. That's the last completed issue. The next unchecked one in ISSUES.md is what's queued.
2. **`Get-Content C:\Users\Business\Desktop\walkthrough.txt -Tail 50`** — the agent's append-only log. Look at the last `EXITING:` line:
    - `done-issue-N` → next issue is N+1
    - `blocked-on-user` → look at the most recent `NEXT-USER-ACTION:` line above it. Drop the file or take the action it names, then trigger the next fire.
    - `blocked-on-session` → Blender wasn't running. Launch Blender 4.2+, click "Connect to Claude" in BlenderMCP tab, then trigger the next fire.
    - `time-budget-reached` → fire ran 3+ hours and stopped to leave headroom. Just trigger the next fire whenever; nothing's wrong.
    - `rate-limit` → Anthropic plan budget hit. Wait for reset (usually next 6h fire), or trigger after reset.
    - `ESCALATED-STOP` → 3 consecutive blocked fires. Read walkthrough + fire logs, fix the underlying cause, then re-enable.
3. **`git branch --list 'wip/*'`** — if there's a WIP branch, the agent had a mid-issue interruption. The next fire will pick it up automatically; you don't need to do anything.
4. **HANDOFF.md** "What's done / what isn't" checklist — coarse-grained progress per phase.

## The autonomous build mechanism

A Windows Scheduled Task `Conjure3D-AutoBuild` fires every 6 hours, runs `claude -p` with the prompt at `C:\Users\Business\Desktop\conjure3d-agent-prompt.txt`, completes as many issues as fit in a 3-hour soft budget (with a hard 5h Task Scheduler timeout), commits each separately, exits.

| File / folder | Purpose |
|---|---|
| `Desktop\walkthrough.txt` | Append-only agent log (state + decisions) |
| `Desktop\inbox\` | Where you drop user-supplied files when blocked |
| `Desktop\deleted\` | Where the agent moves anything it would otherwise delete (soft-delete safety) |
| `Desktop\conjure3d-fires\fire-<ts>.log` | Per-fire stdout/stderr |
| `Desktop\conjure3d-agent-prompt.txt` | The agent's instruction set (read fresh every fire) |
| `Desktop\conjure3d-fire.ps1` | The wrapper script Task Scheduler invokes |

To edit the agent's behavior, modify `conjure3d-agent-prompt.txt` — changes apply on the next fire.

## Common operations

```powershell
# Check status
Get-ScheduledTask -TaskName "Conjure3D-AutoBuild" | Select-Object State
Get-ScheduledTaskInfo -TaskName "Conjure3D-AutoBuild" | Select-Object NextRunTime, LastRunTime, LastTaskResult

# Trigger a fire NOW (skip the 6h wait)
Start-ScheduledTask -TaskName "Conjure3D-AutoBuild"

# Pause autonomous fires
Disable-ScheduledTask -TaskName "Conjure3D-AutoBuild"

# Resume
Enable-ScheduledTask -TaskName "Conjure3D-AutoBuild"

# Stop a currently-running fire
Stop-ScheduledTask -TaskName "Conjure3D-AutoBuild"

# Watch the latest fire log live
$latest = Get-ChildItem "C:\Users\Business\Desktop\conjure3d-fires\fire-*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Get-Content $latest.FullName -Wait

# Tail walkthrough (refreshes when agent writes)
Get-Content "C:\Users\Business\Desktop\walkthrough.txt" -Wait
```

## Common scenarios

**"I see a BLOCKED-USER-INPUT line"** — the next line `NEXT-USER-ACTION:` tells you exactly what to do (drop a file at a specific path, run a specific command, etc.). Do that, then `Start-ScheduledTask` to fire immediately or wait for the next 6h tick.

**"I want to override an autonomous decision"** — the agent committed something you don't want? Don't `git reset --hard` (forbidden by agent rule, and you'd lose work). Instead: open a fresh Claude Code session at the worktree, describe the issue, and have the assistant write a follow-up commit that corrects course.

**"I want to add a new requirement (e.g., Tripo AI as a Meshy alternative)"** — open a Claude Code session, edit `PROMPT.md` / `ISSUES.md` to reflect the new scope, commit. The next autonomous fire will read the updated docs and proceed accordingly.

**"I want to push to GitHub as backup"** — repo isn't on GitHub yet (you said private when this came up). When you want to: create an empty private repo on GitHub, then `git remote add origin <url>` and `git push -u origin claude/sad-bartik-e11c5a`. The autonomous mechanism doesn't care whether there's a remote.

**"The agent did 5 fires in a row that all show ESCALATED-STOP"** — autonomous progression has stalled. Read the latest fire log files in `Desktop\conjure3d-fires\` for stack traces; diagnose; clear or rewrite walkthrough.txt to remove the consecutive blocked count; trigger a fresh fire.

**"Someone closed Claude Code mid-conversation. Did anything get lost?"** — if work was committed, no. If it was an in-flight chat without a commit, that conversation is gone but disk state is preserved. Check `git status` for any uncommitted modifications; check `walkthrough.txt`'s last lines for context.

## Critical rules the agent follows (so you can spot violations)

- **No real Meshy API calls** under any circumstance. Phase F live acceptance is yours.
- **No online account creation.** Ever. You handle Meshy/Tripo accounts.
- **Soft-delete only:** anything that would be `rm`'d goes to `Desktop\deleted\<ts>-<name>` first.
- **Argument lists, not shell strings**, for every subprocess call. Embedded apostrophes are tested by the build path itself.
- **Never log secrets** (API keys) to walkthrough.txt or fire logs.
- **Each issue commits separately** with message `Phase X Issue #N: <short>` — no batching, no PRs from the agent.

If the agent appears to violate any of these, stop the autonomous task, look at the relevant fire log, and tighten the prompt before re-enabling.

## Pointers to deeper docs

- [PROMPT.md](PROMPT.md) — the full build brief (acceptance criteria for every phase)
- [ISSUES.md](ISSUES.md) — 30 issues across phases A-I
- [HANDOFF.md](HANDOFF.md) — architecture decisions and pitfalls
- [docs/pipeline.md](docs/pipeline.md) — geometry pipeline ground truth (Blender ops, slicer recipes)

The agent reads all four at the start of substantive work each fire.
