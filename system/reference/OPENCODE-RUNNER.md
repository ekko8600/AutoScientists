---
name: opencode-runner
---

# OpenCode Runner

AutoScientists uses OpenCode's non-interactive CLI mode for the orchestrator and
for every isolated worker session:

```bash
opencode run --dir /path/to/project "Read runbook.md and execute"
```

`launch.py` copies `system/opencode_runner.py` into every run directory. The
runbook imports its compatibility `Agent(...)` function so the existing task
profiles keep their orchestration shape while workers are launched as:

```bash
opencode run --dir "$FOCUS_ROOT/agents/$AGENT_NAME" --title "..." "<prompt>"
```

Each worker receives its own agent directory as `--dir`, writes stdout and
stderr to `logs/raw/`, and remains isolated from other OpenCode sessions. The
runner supports foreground and background workers plus synchronization with
`wait_for_background_agents()`.

## Authentication

Install OpenCode and authenticate your selected provider before launching a
run:

```bash
curl -fsSL https://opencode.ai/install | bash
opencode auth login
```

OpenCode chooses your configured default model unless you set one of these
environment variables using a `provider/model` value:

```bash
export OPENCODE_MODEL="provider/model"          # fallback for every role
export OPENCODE_GPU_MODEL="provider/model"      # GPU experiment workers
export OPENCODE_ANALYST_MODEL="provider/model"  # analyst workers
export OPENCODE_MONITOR_MODEL="provider/model"  # monitor worker
```

## Permissions

Experiment workers need unattended file edits and shell commands. The runner
sets this inline OpenCode config only for child worker processes:

```bash
OPENCODE_CONFIG_CONTENT='{"permission":"allow"}'
```

Override `OPENCODE_CONFIG_CONTENT` before launch if your environment needs a
stricter policy. Run AutoScientists only against repositories and task inputs
you trust.
