"""
backends.py - Abstract RunBackend and concrete implementations

This module defines the interface for run execution backends and provides
the ClaudeHarnessBackend that wraps existing CLI/Make execution.

Usage:
    from swarm.runtime.backends import ClaudeHarnessBackend
    backend = ClaudeHarnessBackend()
    run_id = backend.start(spec)
    summary = backend.get_summary(run_id)
"""

from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import storage
from .types import (
    BackendCapabilities,
    BackendId,
    RunEvent,
    RunId,
    RunSpec,
    RunState,
    RunStatus,
    RunSummary,
    SDLCStatus,
    generate_run_id,
)

# Module logger
logger = logging.getLogger(__name__)


class RunBackend(ABC):
    """Abstract base class for run execution backends.

    Backends are responsible for:
    - Starting runs (non-blocking, returns immediately)
    - Tracking run status
    - Providing run summaries and events
    - Optionally supporting cancellation
    """

    @property
    @abstractmethod
    def id(self) -> BackendId:
        """Unique identifier for this backend."""
        ...

    @abstractmethod
    def capabilities(self) -> BackendCapabilities:
        """Return what this backend supports."""
        ...

    @abstractmethod
    def start(self, spec: RunSpec) -> RunId:
        """Start a run. Returns immediately with run ID."""
        ...

    @abstractmethod
    def get_summary(self, run_id: RunId) -> Optional[RunSummary]:
        """Get current summary for a run."""
        ...

    @abstractmethod
    def list_summaries(self) -> List[RunSummary]:
        """List all known runs."""
        ...

    @abstractmethod
    def get_events(self, run_id: RunId) -> List[RunEvent]:
        """Get all events for a run."""
        ...

    def cancel(self, run_id: RunId) -> bool:
        """Cancel a running run. Returns True if cancelled."""
        return False  # Default: not supported


class ClaudeHarnessBackend(RunBackend):
    """Backend that wraps existing Claude Code CLI / Make execution.

    This backend:
    - Uses subprocess to run Make targets or slash commands
    - Writes run metadata to swarm/runs/<run_id>/
    - Tracks process state for running jobs
    """

    def __init__(self, repo_root: Optional[Path] = None):
        self._repo_root = repo_root or Path(__file__).resolve().parents[2]
        self._running_processes: Dict[RunId, subprocess.Popen[str]] = {}
        self._lock = threading.Lock()

    @property
    def id(self) -> BackendId:
        return "claude-harness"

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            id="claude-harness",
            label="Claude Code CLI",
            supports_streaming=False,
            supports_events=True,
            supports_cancel=True,
            supports_replay=False,
        )

    def start(self, spec: RunSpec) -> RunId:
        """Start a run by invoking Make/CLI commands."""
        run_id = generate_run_id()
        now = datetime.now(timezone.utc)

        # Create run directory and write initial metadata
        storage.create_run_dir(run_id)
        storage.write_spec(run_id, spec)

        summary = RunSummary(
            id=run_id,
            spec=spec,
            status=RunStatus.PENDING,
            sdlc_status=SDLCStatus.UNKNOWN,
            created_at=now,
            updated_at=now,
        )
        storage.write_summary(run_id, summary)

        # Log initial event
        storage.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="run_created",
                flow_key=spec.flow_keys[0] if spec.flow_keys else "unknown",
                payload={
                    "flows": spec.flow_keys,
                    "backend": spec.backend,
                    "initiator": spec.initiator,
                },
            ),
        )

        # Start execution in background thread
        thread = threading.Thread(
            target=self._execute_run,
            args=(run_id, spec),
            daemon=True,
        )
        thread.start()

        return run_id

    def _execute_run(self, run_id: RunId, spec: RunSpec) -> None:
        """Execute the run in a background thread."""
        now = datetime.now(timezone.utc)

        # Update status to running
        storage.update_summary(
            run_id,
            {
                "status": RunStatus.RUNNING.value,
                "started_at": now.isoformat(),
                "updated_at": now.isoformat(),
            },
        )

        storage.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="run_started",
                flow_key=spec.flow_keys[0] if spec.flow_keys else "unknown",
            ),
        )

        error_msg = None
        final_status = RunStatus.SUCCEEDED
        sdlc_status = SDLCStatus.OK

        try:
            # Execute each flow in sequence
            for flow_key in spec.flow_keys:
                flow_start = datetime.now(timezone.utc)
                storage.append_event(
                    run_id,
                    RunEvent(
                        run_id=run_id,
                        ts=flow_start,
                        kind="flow_start",
                        flow_key=flow_key,
                    ),
                )

                # Build command based on flow
                cmd = self._build_command(flow_key, spec)

                # Execute command
                process = subprocess.Popen(
                    cmd,
                    cwd=str(self._repo_root),
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )

                with self._lock:
                    self._running_processes[run_id] = process

                _, stderr = process.communicate()

                with self._lock:
                    self._running_processes.pop(run_id, None)

                flow_end = datetime.now(timezone.utc)

                if process.returncode != 0:
                    storage.append_event(
                        run_id,
                        RunEvent(
                            run_id=run_id,
                            ts=flow_end,
                            kind="flow_error",
                            flow_key=flow_key,
                            payload={
                                "returncode": process.returncode,
                                "stderr": stderr[:1000] if stderr else None,
                            },
                        ),
                    )
                    final_status = RunStatus.FAILED
                    sdlc_status = SDLCStatus.ERROR
                    if stderr:
                        error_msg = f"Flow {flow_key} failed: {stderr[:500]}"
                    else:
                        error_msg = f"Flow {flow_key} failed with code {process.returncode}"
                    break
                else:
                    storage.append_event(
                        run_id,
                        RunEvent(
                            run_id=run_id,
                            ts=flow_end,
                            kind="flow_end",
                            flow_key=flow_key,
                            payload={
                                "duration_ms": int((flow_end - flow_start).total_seconds() * 1000),
                            },
                        ),
                    )

        except Exception as e:
            logger.exception("Error executing run %s in claude-harness backend", run_id)
            final_status = RunStatus.FAILED
            sdlc_status = SDLCStatus.ERROR
            error_msg = str(e)

        # Update final status
        completed_at = datetime.now(timezone.utc)
        storage.update_summary(
            run_id,
            {
                "status": final_status.value,
                "sdlc_status": sdlc_status.value,
                "completed_at": completed_at.isoformat(),
                "updated_at": completed_at.isoformat(),
                "error": error_msg,
            },
        )

        storage.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=completed_at,
                kind="run_completed",
                flow_key=spec.flow_keys[-1] if spec.flow_keys else "unknown",
                payload={
                    "status": final_status.value,
                    "error": error_msg,
                },
            ),
        )

    def _build_command(self, flow_key: str, spec: RunSpec) -> str:
        """Build the shell command to execute a flow."""
        # Map flow keys to Make targets or Claude commands
        flow_commands = {
            "signal": "make demo-signal",
            "plan": "make demo-plan",
            "build": "make demo-build",
            "gate": "make demo-gate",
            "deploy": "make demo-deploy",
            "wisdom": "make demo-wisdom",
        }

        # Check if custom command provided in params
        if "command" in spec.params:
            return spec.params["command"]

        # Use Make target if available
        if flow_key in flow_commands:
            cmd = flow_commands[flow_key]
            # Add run_id as environment variable
            return f"RUN_ID={spec.params.get('run_id', '')} {cmd}"

        # Fallback to slash command style
        return f"echo 'Flow {flow_key} would run here'"

    def get_summary(self, run_id: RunId) -> Optional[RunSummary]:
        """Get summary from disk."""
        return storage.read_summary(run_id)

    def list_summaries(self) -> List[RunSummary]:
        """List all runs with summaries."""
        summaries: List[RunSummary] = []
        for rid in storage.list_runs():
            summary = storage.read_summary(rid)
            if summary:
                summaries.append(summary)
        return summaries

    def get_events(self, run_id: RunId) -> List[RunEvent]:
        """Get events from disk."""
        return storage.read_events(run_id)

    def cancel(self, run_id: RunId) -> bool:
        """Cancel a running process."""
        with self._lock:
            process = self._running_processes.get(run_id)
            if process:
                process.terminate()
                self._running_processes.pop(run_id, None)

                # Update status
                now = datetime.now(timezone.utc)
                storage.update_summary(
                    run_id,
                    {
                        "status": RunStatus.CANCELED.value,
                        "completed_at": now.isoformat(),
                        "updated_at": now.isoformat(),
                    },
                )
                storage.append_event(
                    run_id,
                    RunEvent(
                        run_id=run_id,
                        ts=now,
                        kind="run_canceled",
                        flow_key="unknown",
                    ),
                )
                return True
        return False


class AgentSDKBackend(RunBackend):
    """Backend that uses the Claude Agent SDK (stub for future implementation)."""

    @property
    def id(self) -> BackendId:
        return "claude-agent-sdk"

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            id="claude-agent-sdk",
            label="Claude Agent SDK",
            supports_streaming=True,
            supports_events=True,
            supports_cancel=True,
            supports_replay=True,
        )

    def start(self, spec: RunSpec) -> RunId:
        raise NotImplementedError("Agent SDK backend not yet implemented")

    def get_summary(self, run_id: RunId) -> Optional[RunSummary]:
        return storage.read_summary(run_id)

    def list_summaries(self) -> List[RunSummary]:
        return []

    def get_events(self, run_id: RunId) -> List[RunEvent]:
        return storage.read_events(run_id)


class GeminiCliBackend(RunBackend):
    """Backend that uses Gemini CLI for run execution.

    This backend executes flows using the Gemini CLI tool, streaming JSONL
    events and mapping them to the standard RunEvent format.

    The Gemini CLI is expected to output JSONL events with types:
    - init: Backend initialization
    - message: Assistant text output
    - tool_use: Tool invocation started
    - tool_result: Tool invocation completed
    - error: Error occurred
    - result: Final completion result

    TODO: Implementation status (v0.7.1)
    ------------------------------------
    Currently this backend uses a stub command that echoes simulated JSONL events.
    The real implementation will use `gemini --output-format stream-json` as
    documented in the Gemini CLI docs.

    When implementing for real:
    1. Replace _build_command() stub with actual `gemini` CLI invocation
    2. The CLI should be called with `--output-format stream-json`
    3. Events map to RunEvent via _map_gemini_event()
    4. See docs/runtime/gemini-cli-backend.md for full integration plan
    """

    def __init__(self, repo_root: Optional[Path] = None):
        self._repo_root = repo_root or Path(__file__).resolve().parents[2]
        self._running_processes: Dict[RunId, subprocess.Popen[str]] = {}
        self._lock = threading.Lock()

        # CLI configuration
        self.gemini_cmd = os.environ.get("SWARM_GEMINI_CLI", "gemini")
        self.stub_mode = os.environ.get("SWARM_GEMINI_STUB", "1") == "1"
        self.cli_available = shutil.which(self.gemini_cmd) is not None

    @property
    def id(self) -> BackendId:
        return "gemini-cli"

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            id="gemini-cli",
            label="Gemini CLI",
            supports_streaming=True,
            supports_events=True,
            supports_cancel=True,
            supports_replay=False,
        )

    def start(self, spec: RunSpec) -> RunId:
        """Start a run by invoking Gemini CLI commands."""
        run_id = generate_run_id()
        now = datetime.now(timezone.utc)

        # Create run directory and write initial metadata
        storage.create_run_dir(run_id)
        storage.write_spec(run_id, spec)

        summary = RunSummary(
            id=run_id,
            spec=spec,
            status=RunStatus.PENDING,
            sdlc_status=SDLCStatus.UNKNOWN,
            created_at=now,
            updated_at=now,
        )
        storage.write_summary(run_id, summary)

        # Log initial event
        storage.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="run_created",
                flow_key=spec.flow_keys[0] if spec.flow_keys else "unknown",
                payload={
                    "flows": spec.flow_keys,
                    "backend": spec.backend,
                    "initiator": spec.initiator,
                },
            ),
        )

        # Start execution in background thread
        thread = threading.Thread(
            target=self._execute_run,
            args=(run_id, spec),
            daemon=True,
        )
        thread.start()

        return run_id

    def _execute_run(self, run_id: RunId, spec: RunSpec) -> None:
        """Execute the run in a background thread using Gemini CLI."""
        import json

        now = datetime.now(timezone.utc)

        # Update status to running
        storage.update_summary(
            run_id,
            {
                "status": RunStatus.RUNNING.value,
                "started_at": now.isoformat(),
                "updated_at": now.isoformat(),
            },
        )

        storage.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="run_started",
                flow_key=spec.flow_keys[0] if spec.flow_keys else "unknown",
                payload={"backend": "gemini-cli"},
            ),
        )

        # Log backend initialization event with mode indicator
        mode = "stub" if self.stub_mode or not self.cli_available else "real"
        storage.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=datetime.now(timezone.utc),
                kind="backend_init",
                flow_key=spec.flow_keys[0] if spec.flow_keys else "unknown",
                payload={
                    "backend": "gemini-cli",
                    "version": "1.0.0",
                    "mode": mode,
                    "cli_available": self.cli_available,
                },
            ),
        )

        error_msg = None
        final_status = RunStatus.SUCCEEDED
        sdlc_status = SDLCStatus.OK

        try:
            # Execute each flow in sequence
            for flow_key in spec.flow_keys:
                flow_start = datetime.now(timezone.utc)
                storage.append_event(
                    run_id,
                    RunEvent(
                        run_id=run_id,
                        ts=flow_start,
                        kind="flow_start",
                        flow_key=flow_key,
                    ),
                )

                # Build Gemini CLI command (pass run_id explicitly)
                cmd = self._build_command(flow_key, run_id, spec)

                # Execute command and stream JSONL output
                process = subprocess.Popen(
                    cmd,
                    cwd=str(self._repo_root),
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )

                with self._lock:
                    self._running_processes[run_id] = process

                # Process JSONL output line by line for streaming
                if process.stdout:
                    for line in process.stdout:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            gemini_event = json.loads(line)
                            mapped_event = self._map_gemini_event(run_id, flow_key, gemini_event)
                            if mapped_event:
                                storage.append_event(run_id, mapped_event)
                        except json.JSONDecodeError:
                            # Non-JSON output - log as text event
                            storage.append_event(
                                run_id,
                                RunEvent(
                                    run_id=run_id,
                                    ts=datetime.now(timezone.utc),
                                    kind="log",
                                    flow_key=flow_key,
                                    payload={"message": line},
                                ),
                            )

                # Wait for process to complete
                _, stderr = process.communicate()

                with self._lock:
                    self._running_processes.pop(run_id, None)

                flow_end = datetime.now(timezone.utc)

                if process.returncode != 0:
                    storage.append_event(
                        run_id,
                        RunEvent(
                            run_id=run_id,
                            ts=flow_end,
                            kind="flow_error",
                            flow_key=flow_key,
                            payload={
                                "returncode": process.returncode,
                                "stderr": stderr[:1000] if stderr else None,
                            },
                        ),
                    )
                    final_status = RunStatus.FAILED
                    sdlc_status = SDLCStatus.ERROR
                    error_msg = (
                        f"Flow {flow_key} failed: {stderr[:500]}"
                        if stderr
                        else f"Flow {flow_key} failed with code {process.returncode}"
                    )
                    break
                else:
                    storage.append_event(
                        run_id,
                        RunEvent(
                            run_id=run_id,
                            ts=flow_end,
                            kind="flow_end",
                            flow_key=flow_key,
                            payload={
                                "duration_ms": int((flow_end - flow_start).total_seconds() * 1000),
                            },
                        ),
                    )

        except Exception as e:
            logger.exception("Error executing run %s in gemini-cli backend", run_id)
            final_status = RunStatus.FAILED
            sdlc_status = SDLCStatus.ERROR
            error_msg = str(e)

        # Update final status
        completed_at = datetime.now(timezone.utc)
        storage.update_summary(
            run_id,
            {
                "status": final_status.value,
                "sdlc_status": sdlc_status.value,
                "completed_at": completed_at.isoformat(),
                "updated_at": completed_at.isoformat(),
                "error": error_msg,
            },
        )

        storage.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=completed_at,
                kind="run_completed",
                flow_key=spec.flow_keys[-1] if spec.flow_keys else "unknown",
                payload={
                    "status": final_status.value,
                    "error": error_msg,
                },
            ),
        )

    # -------------------------------------------------------------------------
    # TOML Commands vs Backend Prompts: Design Separation
    # -------------------------------------------------------------------------
    # There are two ways to invoke Gemini for Swarm flows:
    #
    # 1. INTERACTIVE CLI (Human Use):
    #    Location: .gemini/commands/swarm/*.toml
    #    Purpose: Human operators use these with `gemini /swarm/<flow>` to
    #             interactively execute flows from the terminal.
    #    Format: TOML files with description + prompt, supporting @{} file refs.
    #    Example: `gemini /swarm/signal my-run-id`
    #
    # 2. PROGRAMMATIC BACKEND (Flow Studio Use):
    #    Location: This file (_build_prompt, _build_command)
    #    Purpose: Flow Studio's runtime calls Gemini via subprocess with
    #             explicit --prompt arguments for machine-driven execution.
    #    Format: Direct CLI invocation with --output-format stream-json.
    #    Example: `gemini --output-format stream-json --prompt "..."`
    #
    # Why the separation?
    # - TOML commands are optimized for human ergonomics (readable prompts,
    #   file references, help text).
    # - Backend prompts are optimized for programmatic control (structured
    #   output, run_id injection, event streaming).
    #
    # Future: A command-driven backend variant could invoke the TOML commands
    # directly (e.g., `gemini /swarm/signal {run_id}`), but this would require
    # capturing and parsing their output differently than stream-json format.
    # -------------------------------------------------------------------------

    def _build_prompt(self, flow_key: str, run_id: RunId, spec: RunSpec) -> str:
        """Build the prompt for the Gemini CLI.

        Includes flow context, run ID, and instructions for structured output.

        Args:
            flow_key: The flow being executed (signal, plan, build, etc.)
            run_id: The run identifier (passed explicitly, not from spec.params)
            spec: The run specification
        """
        title = spec.params.get("title", flow_key)

        return f"""You are the Gemini CLI backend executing a Swarm flow step.

Flow: {flow_key}
Run ID: {run_id}
Title: {title}

Instructions:
1. Read the flow spec from swarm/flows/flow-{flow_key}.md
2. Execute the flow step according to the spec
3. Write outputs to swarm/runs/{run_id}/{flow_key}/ following RUN_BASE conventions
4. Stream your progress as structured events

Be concise and focused on the task."""

    def _build_stub_command(self, flow_key: str, run_id: RunId, spec: RunSpec) -> str:
        """Build a stub command that simulates Gemini JSONL output for testing.

        Args:
            flow_key: The flow being executed
            run_id: The run identifier (passed explicitly)
            spec: The run specification
        """
        tool_input = f'{{"path": "swarm/flows/flow-{flow_key}.md"}}'
        stub_events = [
            f'{{"type": "init", "backend": "gemini-cli", "flow": "{flow_key}"}}',
            f'{{"type": "text", "message": "Starting flow {flow_key}"}}',
            f'{{"type": "tool_use", "tool": "read", "input": {tool_input}}}',
            '{{"type": "tool_result", "tool": "read", "success": true}}',
            f'{{"type": "result", "flow": "{flow_key}", "status": "complete"}}',
        ]
        events_json = "\\n".join(stub_events)
        return f'echo -e "{events_json}" && RUN_ID={run_id} echo "Flow {flow_key} completed"'

    def _build_command(self, flow_key: str, run_id: RunId, spec: RunSpec) -> str:
        """Build the Gemini CLI command to execute a flow.

        Uses real `gemini` CLI when available and SWARM_GEMINI_STUB=0.
        Falls back to stub for CI or when CLI is not installed.

        Args:
            flow_key: The flow being executed
            run_id: The run identifier (passed explicitly from _execute_run)
            spec: The run specification
        """
        # Allow explicit command override for testing
        if "command" in spec.params:
            return spec.params["command"]

        # Use stub when stub_mode is enabled or CLI not available
        if self.stub_mode or not self.cli_available:
            logger.debug(
                "GeminiCliBackend using stub (stub_mode=%s, cli_available=%s)",
                self.stub_mode,
                self.cli_available,
            )
            return self._build_stub_command(flow_key, run_id, spec)

        # Build real gemini CLI command
        prompt = self._build_prompt(flow_key, run_id, spec)

        args = [
            self.gemini_cmd,
            "--output-format",
            "stream-json",
            "--prompt",
            prompt,
        ]

        # Use shell quoting since we run with shell=True
        return " ".join(shlex.quote(a) for a in args)

    def _map_gemini_event(
        self, run_id: RunId, flow_key: str, gemini_event: Dict[str, Any]
    ) -> Optional[RunEvent]:
        """Map Gemini JSONL events to RunEvent format.

        Gemini CLI stream-json event types:
        - init: Session initialization
        - message: Text output (has 'role' field: user/assistant)
        - tool_use: Tool invocation started
        - tool_result: Tool invocation completed
        - error: Error occurred
        - result: Final completion result
        """
        event_type = gemini_event.get("type", "unknown")
        now = datetime.now(timezone.utc)

        # Parse timestamp if present
        ts_str = gemini_event.get("timestamp")
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except ValueError:
                logger.warning("Failed to parse Gemini event timestamp: %r", ts_str)
                ts = now
        else:
            ts = now

        # Map Gemini event types to RunEvent kinds
        if event_type == "message":
            role = gemini_event.get("role", "assistant")
            kind = "assistant_message" if role == "assistant" else "user_message"
        elif event_type == "tool_use":
            kind = "tool_start"
        elif event_type == "tool_result":
            kind = "tool_end"
        elif event_type == "error":
            kind = "error"
        elif event_type == "result":
            kind = "step_complete"
        elif event_type == "init":
            kind = "backend_init"
        elif event_type == "text":  # Legacy stub format
            kind = "log"
        else:
            kind = event_type

        # Build payload based on event type
        payload: Dict[str, Any] = {}
        if event_type == "init":
            payload = {
                "backend": gemini_event.get("backend"),
                "flow": gemini_event.get("flow"),
            }
        elif event_type == "message":
            payload = {
                "role": gemini_event.get("role"),
                "content": gemini_event.get("content", ""),
            }
        elif event_type == "tool_use":
            payload = {
                "tool": gemini_event.get("tool") or gemini_event.get("name"),
                "input": gemini_event.get("input") or gemini_event.get("args"),
            }
        elif event_type == "tool_result":
            # Be conservative: default to False if success field is missing
            success = gemini_event.get("success")
            if success is None:
                logger.warning("Gemini tool_result missing 'success' field: %r", gemini_event)
                success = False
            payload = {
                "tool": gemini_event.get("tool") or gemini_event.get("name"),
                "success": success,
                "output": gemini_event.get("output") or gemini_event.get("result"),
            }
        elif event_type == "text":
            payload = {"message": gemini_event.get("message")}
        elif event_type == "error":
            payload = {
                "error": gemini_event.get("error") or gemini_event.get("message"),
            }
        elif event_type == "result":
            payload = {
                "flow": gemini_event.get("flow"),
                "status": gemini_event.get("status"),
            }
        else:
            # Pass through unknown events
            payload = gemini_event

        return RunEvent(
            run_id=run_id,
            ts=ts,
            kind=kind,
            flow_key=flow_key,
            payload=payload,
        )

    def get_summary(self, run_id: RunId) -> Optional[RunSummary]:
        """Get summary from disk."""
        return storage.read_summary(run_id)

    def list_summaries(self) -> List[RunSummary]:
        """List all runs with summaries."""
        summaries: List[RunSummary] = []
        for rid in storage.list_runs():
            summary = storage.read_summary(rid)
            if summary:
                summaries.append(summary)
        return summaries

    def get_events(self, run_id: RunId) -> List[RunEvent]:
        """Get events from disk."""
        return storage.read_events(run_id)

    def cancel(self, run_id: RunId) -> bool:
        """Cancel a running process."""
        with self._lock:
            process = self._running_processes.get(run_id)
            if process:
                process.terminate()
                self._running_processes.pop(run_id, None)

                # Update status
                now = datetime.now(timezone.utc)
                storage.update_summary(
                    run_id,
                    {
                        "status": RunStatus.CANCELED.value,
                        "completed_at": now.isoformat(),
                        "updated_at": now.isoformat(),
                    },
                )
                storage.append_event(
                    run_id,
                    RunEvent(
                        run_id=run_id,
                        ts=now,
                        kind="run_canceled",
                        flow_key="unknown",
                    ),
                )
                return True
        return False


class GeminiStepwiseBackend(RunBackend):
    """Backend that uses GeminiStepOrchestrator for stepwise flow execution.

    This backend provides fine-grained control over flow execution by
    iterating through each step of a flow as a separate Gemini CLI call.
    This enables:

    - Per-step observability with events logged at step boundaries
    - Context handoff between steps (previous outputs inform next step)
    - Better error isolation (failures are step-scoped)
    - Teaching mode support (can pause/resume at step boundaries)

    Unlike GeminiCliBackend which executes entire flows in one call, this
    backend delegates to GeminiStepOrchestrator which breaks down flows
    into individual steps.
    """

    def __init__(self, repo_root: Optional[Path] = None):
        self._repo_root = repo_root or Path(__file__).resolve().parents[2]
        self._orchestrator: Optional[Any] = None  # Type: GeminiStepOrchestrator
        self._lock = threading.Lock()

    def _get_orchestrator(self) -> Any:
        """Lazy-initialize the orchestrator (thread-safe).

        Uses lazy import to avoid circular dependency with orchestrator module.
        Uses double-checked locking to ensure thread-safe initialization.
        """
        if self._orchestrator is None:
            with self._lock:
                # Double-check after acquiring lock
                if self._orchestrator is None:
                    # Lazy import to avoid circular dependency
                    from .orchestrator import get_orchestrator

                    self._orchestrator = get_orchestrator(repo_root=self._repo_root)
        return self._orchestrator

    @property
    def id(self) -> BackendId:
        return "gemini-step-orchestrator"

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            id="gemini-step-orchestrator",
            label="Gemini CLI (stepwise)",
            supports_streaming=True,
            supports_events=True,
            supports_cancel=True,
            supports_replay=False,
        )

    def start(self, spec: RunSpec) -> RunId:
        """Start a stepwise run by invoking the orchestrator.

        Synchronous Guarantees (on return):
        - run_id: Unique ID generated (format: run-YYYYMMDD-HHMMSS-xxxxxx)
        - run directory: swarm/runs/<run_id>/ created
        - spec.json: RunSpec persisted
        - meta.json: Initial RunSummary with status=PENDING
        - events.jsonl: run_created event with stepwise=True

        Asynchronous Work (background thread):
        - Actual step execution delegated to orchestrator
        - Status updates (RUNNING, SUCCEEDED, FAILED)
        - Poll get_summary() or get_events() to track progress
        """
        run_id = generate_run_id()
        now = datetime.now(timezone.utc)

        # Create run directory and write initial metadata
        storage.create_run_dir(run_id)
        storage.write_spec(run_id, spec)

        summary = RunSummary(
            id=run_id,
            spec=spec,
            status=RunStatus.PENDING,
            sdlc_status=SDLCStatus.UNKNOWN,
            created_at=now,
            updated_at=now,
        )
        storage.write_summary(run_id, summary)

        # Log initial event with stepwise flag
        storage.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="run_created",
                flow_key=spec.flow_keys[0] if spec.flow_keys else "unknown",
                payload={
                    "flows": spec.flow_keys,
                    "backend": "gemini-step-orchestrator",
                    "initiator": spec.initiator,
                    "stepwise": True,
                },
            ),
        )

        # Start orchestrator execution in background thread
        thread = threading.Thread(
            target=self._execute_stepwise,
            args=(run_id, spec),
            daemon=True,
        )
        thread.start()

        return run_id

    def _execute_stepwise(self, run_id: RunId, spec: RunSpec) -> None:
        """Execute the stepwise flow via the orchestrator.

        This method runs in a background thread and delegates to the
        GeminiStepOrchestrator for step-by-step execution.
        """
        orchestrator = self._get_orchestrator()

        # Execute each flow in the spec
        for flow_key in spec.flow_keys:
            try:
                # Create RunState for this flow execution
                run_state = RunState(
                    run_id=run_id,
                    flow_key=flow_key,
                    status="pending",
                    timestamp=datetime.now(timezone.utc),
                )
                storage.write_run_state(run_id, run_state)

                # The orchestrator handles its own run creation, but we want
                # to use our run_id. We call run_stepwise_flow which creates
                # its own run_id, so we need to manually drive the execution.
                # For now, we invoke the orchestrator's internal execution method.
                orchestrator._execute_stepwise(
                    run_id=run_id,
                    flow_key=flow_key,
                    flow_def=orchestrator._flow_registry.get_flow(flow_key),
                    spec=spec,
                    run_state=run_state,
                    start_step=None,
                    end_step=None,
                )
            except Exception as e:
                logger.exception(
                    "Error in stepwise execution for run %s, flow %s",
                    run_id,
                    flow_key,
                )
                # Update summary with error
                now = datetime.now(timezone.utc)
                storage.update_summary(
                    run_id,
                    {
                        "status": RunStatus.FAILED.value,
                        "sdlc_status": SDLCStatus.ERROR.value,
                        "completed_at": now.isoformat(),
                        "updated_at": now.isoformat(),
                        "error": str(e),
                    },
                )
                return  # Exit on error

        # All flows completed successfully - update status
        now = datetime.now(timezone.utc)
        storage.update_summary(
            run_id,
            {
                "status": RunStatus.SUCCEEDED.value,
                "sdlc_status": SDLCStatus.OK.value,
                "completed_at": now.isoformat(),
                "updated_at": now.isoformat(),
            },
        )

    def get_summary(self, run_id: RunId) -> Optional[RunSummary]:
        """Get summary from disk."""
        return storage.read_summary(run_id)

    def list_summaries(self) -> List[RunSummary]:
        """List all runs with summaries."""
        summaries: List[RunSummary] = []
        for rid in storage.list_runs():
            summary = storage.read_summary(rid)
            if summary:
                summaries.append(summary)
        return summaries

    def get_events(self, run_id: RunId) -> List[RunEvent]:
        """Get events from disk."""
        return storage.read_events(run_id)

    def cancel(self, run_id: RunId) -> bool:
        """Cancel a running stepwise execution.

        Note: Currently returns False as the orchestrator does not yet
        support mid-execution cancellation. The orchestrator would need
        to track running state per run_id to support this.
        """
        # TODO: Implement cancellation by tracking orchestrator run state
        return False


class ClaudeStepwiseBackend(RunBackend):
    """Backend that uses ClaudeStepEngine for stepwise flow execution.

    This backend provides fine-grained control over flow execution by
    iterating through each step of a flow as a separate Claude Agent SDK call.
    This enables:

    - Per-step observability with events logged at step boundaries
    - Context handoff between steps (previous outputs inform next step)
    - Better error isolation (failures are step-scoped)
    - Teaching mode support (can pause/resume at step boundaries)

    Unlike ClaudeHarnessBackend which executes entire flows in one call, this
    backend delegates to an orchestrator with ClaudeStepEngine which breaks
    down flows into individual steps.

    Contract Tests:
        The synchronous contract of start() is enforced by:
        tests/test_claude_stepwise_backend.py::test_start_creates_run
    """

    def __init__(self, repo_root: Optional[Path] = None):
        self._repo_root = repo_root or Path(__file__).resolve().parents[2]
        self._orchestrator: Optional[Any] = None
        self._lock = threading.Lock()

    def _get_orchestrator(self) -> Any:
        """Lazy-initialize the orchestrator with ClaudeStepEngine (thread-safe).

        Uses lazy import to avoid circular dependency with orchestrator module.
        Uses double-checked locking to ensure thread-safe initialization.
        """
        if self._orchestrator is None:
            with self._lock:
                # Double-check after acquiring lock
                if self._orchestrator is None:
                    # Lazy import to avoid circular dependency
                    from .engines import ClaudeStepEngine
                    from .orchestrator import get_orchestrator

                    self._orchestrator = get_orchestrator(
                        engine=ClaudeStepEngine(self._repo_root),
                        repo_root=self._repo_root,
                    )
        return self._orchestrator

    @property
    def id(self) -> BackendId:
        return "claude-step-orchestrator"

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            id="claude-step-orchestrator",
            label="Claude Agent SDK (stepwise)",
            supports_streaming=True,
            supports_events=True,
            supports_cancel=True,
            supports_replay=False,
        )

    def start(self, spec: RunSpec) -> RunId:
        """Start a stepwise run by invoking the orchestrator.

        Synchronous Guarantees (on return):
        - run_id: Unique ID generated (format: run-YYYYMMDD-HHMMSS-xxxxxx)
        - run directory: swarm/runs/<run_id>/ created
        - spec.json: RunSpec persisted
        - meta.json: Initial RunSummary with status=PENDING
        - events.jsonl: run_created event with stepwise=True

        Asynchronous Work (background thread):
        - Actual step execution delegated to orchestrator
        - Status updates (RUNNING, SUCCEEDED, FAILED)
        - Poll get_summary() or get_events() to track progress

        See Also:
            tests/test_claude_stepwise_backend.py::test_start_creates_run
            for contract enforcement tests.
        """
        run_id = generate_run_id()
        now = datetime.now(timezone.utc)

        # Create run directory and write initial metadata
        storage.create_run_dir(run_id)
        storage.write_spec(run_id, spec)

        summary = RunSummary(
            id=run_id,
            spec=spec,
            status=RunStatus.PENDING,
            sdlc_status=SDLCStatus.UNKNOWN,
            created_at=now,
            updated_at=now,
        )
        storage.write_summary(run_id, summary)

        # Log initial event with stepwise flag
        storage.append_event(
            run_id,
            RunEvent(
                run_id=run_id,
                ts=now,
                kind="run_created",
                flow_key=spec.flow_keys[0] if spec.flow_keys else "unknown",
                payload={
                    "flows": spec.flow_keys,
                    "backend": "claude-step-orchestrator",
                    "initiator": spec.initiator,
                    "stepwise": True,
                },
            ),
        )

        # Start orchestrator execution in background thread
        thread = threading.Thread(
            target=self._execute_stepwise,
            args=(run_id, spec),
            daemon=True,
        )
        thread.start()

        return run_id

    def _execute_stepwise(self, run_id: RunId, spec: RunSpec) -> None:
        """Execute the stepwise flow via the orchestrator.

        This method runs in a background thread and delegates to the
        orchestrator with ClaudeStepEngine for step-by-step execution.
        """
        orchestrator = self._get_orchestrator()

        # Execute each flow in the spec
        for flow_key in spec.flow_keys:
            try:
                # Create RunState for this flow execution
                run_state = RunState(
                    run_id=run_id,
                    flow_key=flow_key,
                    status="pending",
                    timestamp=datetime.now(timezone.utc),
                )
                storage.write_run_state(run_id, run_state)

                # The orchestrator handles its own run creation, but we want
                # to use our run_id. We call run_stepwise_flow which creates
                # its own run_id, so we need to manually drive the execution.
                # For now, we invoke the orchestrator's internal execution method.
                orchestrator._execute_stepwise(
                    run_id=run_id,
                    flow_key=flow_key,
                    flow_def=orchestrator._flow_registry.get_flow(flow_key),
                    spec=spec,
                    run_state=run_state,
                    start_step=None,
                    end_step=None,
                )
            except Exception as e:
                logger.exception(
                    "Error in stepwise execution for run %s, flow %s",
                    run_id,
                    flow_key,
                )
                # Update summary with error
                now = datetime.now(timezone.utc)
                storage.update_summary(
                    run_id,
                    {
                        "status": RunStatus.FAILED.value,
                        "sdlc_status": SDLCStatus.ERROR.value,
                        "completed_at": now.isoformat(),
                        "updated_at": now.isoformat(),
                        "error": str(e),
                    },
                )
                return  # Exit on error

        # All flows completed successfully - update status
        now = datetime.now(timezone.utc)
        storage.update_summary(
            run_id,
            {
                "status": RunStatus.SUCCEEDED.value,
                "sdlc_status": SDLCStatus.OK.value,
                "completed_at": now.isoformat(),
                "updated_at": now.isoformat(),
            },
        )

    def get_summary(self, run_id: RunId) -> Optional[RunSummary]:
        """Get summary from disk."""
        return storage.read_summary(run_id)

    def list_summaries(self) -> List[RunSummary]:
        """List all runs with summaries."""
        summaries: List[RunSummary] = []
        for rid in storage.list_runs():
            summary = storage.read_summary(rid)
            if summary:
                summaries.append(summary)
        return summaries

    def get_events(self, run_id: RunId) -> List[RunEvent]:
        """Get events from disk."""
        return storage.read_events(run_id)

    def cancel(self, run_id: RunId) -> bool:
        """Cancel a running stepwise execution.

        Note: Currently returns False as the orchestrator does not yet
        support mid-execution cancellation. The orchestrator would need
        to track running state per run_id to support this.
        """
        # TODO: Implement cancellation by tracking orchestrator run state
        return False


# Registry of available backends
_BACKEND_REGISTRY: dict[BackendId, type[RunBackend]] = {
    "claude-harness": ClaudeHarnessBackend,
    "claude-agent-sdk": AgentSDKBackend,
    "gemini-cli": GeminiCliBackend,
    "gemini-step-orchestrator": GeminiStepwiseBackend,
    "claude-step-orchestrator": ClaudeStepwiseBackend,
}


def get_backend(backend_id: BackendId) -> RunBackend:
    """Get a backend instance by ID."""
    backend_class = _BACKEND_REGISTRY.get(backend_id)
    if not backend_class:
        raise ValueError(f"Unknown backend: {backend_id}")
    return backend_class()


def list_backends() -> List[BackendCapabilities]:
    """List capabilities of all registered backends."""
    return [get_backend(bid).capabilities() for bid in _BACKEND_REGISTRY]
