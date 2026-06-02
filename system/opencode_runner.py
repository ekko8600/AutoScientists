#!/usr/bin/env python3
"""OpenCode process launcher for AutoScientists orchestrator sessions.

The runbook imports ``Agent`` from this module so existing task profiles keep
using the same orchestration shape while each worker runs as an isolated
``opencode run`` session.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


_BACKGROUND_AGENTS: list["OpenCodeAgent"] = []
_AGENT_NAME_RE = re.compile(r"^You are\s+([^\s.]+)", re.MULTILINE)
_FOCUS_ROOT_RE = re.compile(r"^FOCUS_ROOT=(.+)$", re.MULTILINE)
_ENV_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$", re.MULTILINE)


@dataclass
class OpenCodeAgent:
    """A launched OpenCode worker session."""

    description: str
    command: list[str]
    process: subprocess.Popen[str]
    log_path: Path
    log_handle: object

    def wait(self, timeout: float | None = None) -> int:
        """Wait for the worker and close its raw-log file."""
        try:
            return self.process.wait(timeout=timeout)
        finally:
            if self.process.poll() is not None and not self.log_handle.closed:
                self.log_handle.close()

    def poll(self) -> int | None:
        """Return the worker exit code, if it has finished."""
        return self.process.poll()


def _prompt_value(prompt: str, pattern: re.Pattern[str], default: str) -> str:
    match = pattern.search(prompt)
    return match.group(1).strip() if match else default


def _agent_environment(prompt: str, agent_name: str) -> dict[str, str]:
    env = os.environ.copy()
    # Autonomous experiment workers must be able to edit files, run training,
    # and read trusted files elsewhere in FOCUS_ROOT. Inline config is the
    # official runtime override supported by OpenCode. Users can provide a
    # stricter policy by defining OPENCODE_CONFIG_CONTENT before launch.
    env.setdefault("OPENCODE_CONFIG_CONTENT", json.dumps({"permission": "allow"}))
    for key, value in _ENV_RE.findall(prompt):
        if key in {"CUDA_VISIBLE_DEVICES", "MODE", "BIOMLBENCH", "TIME_REMAINING_MINUTES", "DEADLINE_BUFFER_MINUTES"}:
            env[key] = value.strip().strip('"')
    env["AUTOSCIENTISTS_AGENT_NAME"] = agent_name
    return env


def _configured_model(agent_name: str, requested_model: str | None) -> str | None:
    role = "ANALYST" if "analyst" in agent_name else "MONITOR" if "monitor" in agent_name else "GPU"
    return (
        os.environ.get(f"OPENCODE_{role}_MODEL")
        or os.environ.get("OPENCODE_MODEL")
        or (requested_model if requested_model and "/" in requested_model else None)
    )


def Agent(
    *,
    description: str,
    prompt: str,
    run_in_background: bool = False,
    model: str | None = None,
) -> OpenCodeAgent:
    """Launch one isolated AutoScientists worker through ``opencode run``.

    ``model`` is accepted for compatibility with the original runbook. OpenCode
    model IDs must use ``provider/model`` form, so short legacy labels such as
    ``sonnet`` are ignored unless mapped through an ``OPENCODE_*_MODEL`` env var.
    """
    agent_name = _prompt_value(prompt, _AGENT_NAME_RE, "autoscientists-agent")
    focus_root = Path(_prompt_value(prompt, _FOCUS_ROOT_RE, os.getcwd())).expanduser().resolve()
    workdir = focus_root / "agents" / agent_name
    if not workdir.is_dir():
        raise RuntimeError(f"Agent directory does not exist: {workdir}")

    logs_dir = focus_root / "logs" / "raw"
    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    log_path = logs_dir / f"{agent_name}_{timestamp}.log"
    log_handle = log_path.open("w", encoding="utf-8")

    command = ["opencode", "run", "--dir", str(workdir), "--title", description]
    configured_model = _configured_model(agent_name, model)
    if configured_model:
        command.extend(["--model", configured_model])
    command.append(prompt)

    print(f"Launching OpenCode worker: {agent_name}")
    print(f"  command: {shlex.join(command[:-1])} <prompt>")
    print(f"  log: {log_path}")
    try:
        process = subprocess.Popen(
            command,
            cwd=workdir,
            env=_agent_environment(prompt, agent_name),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except Exception:
        log_handle.close()
        raise

    worker = OpenCodeAgent(description, command, process, log_path, log_handle)
    if run_in_background:
        _BACKGROUND_AGENTS.append(worker)
    else:
        return_code = worker.wait()
        if return_code != 0:
            raise RuntimeError(f"OpenCode worker failed ({return_code}); inspect {log_path}")
    return worker


def wait_for_background_agents(agents: Iterable[OpenCodeAgent] | None = None) -> None:
    """Wait for background workers and raise after all workers have settled."""
    selected = list(agents) if agents is not None else list(_BACKGROUND_AGENTS)
    failures: list[str] = []
    for worker in selected:
        return_code = worker.wait()
        if worker in _BACKGROUND_AGENTS:
            _BACKGROUND_AGENTS.remove(worker)
        if return_code != 0:
            failures.append(f"{worker.description}: exit {return_code} ({worker.log_path})")
    if failures:
        raise RuntimeError("OpenCode worker failures:\n" + "\n".join(failures))


def reap_background_agents() -> None:
    """Close completed workers without blocking; raise if one failed."""
    completed = [worker for worker in _BACKGROUND_AGENTS if worker.poll() is not None]
    if completed:
        wait_for_background_agents(completed)


def _main() -> None:
    parser = argparse.ArgumentParser(description="Launch one AutoScientists OpenCode worker")
    parser.add_argument("--description", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--background", action="store_true")
    parser.add_argument("--model")
    args = parser.parse_args()
    Agent(
        description=args.description,
        prompt=args.prompt,
        run_in_background=args.background,
        model=args.model,
    )


if __name__ == "__main__":
    _main()
