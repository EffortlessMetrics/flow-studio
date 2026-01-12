#!/usr/bin/env python3
"""
Flow Studio smoke test runner.

Produces receipt-backed artifacts proving Flow Studio works:
- Server startup
- Core endpoint availability
- Basic latency
- Environment snapshot

Artifacts written to: artifacts/flowstudio_smoke/<timestamp>/

Usage:
    uv run swarm/tools/flowstudio_smoke.py
    # or with existing server:
    FLOWSTUDIO_SKIP_SERVER=1 uv run swarm/tools/flowstudio_smoke.py
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Artifact directory
ART_DIR = Path("artifacts/flowstudio_smoke") / time.strftime("%Y%m%d-%H%M%S")

HOST = os.getenv("FLOWSTUDIO_HOST", "127.0.0.1")
PORT = int(os.getenv("FLOWSTUDIO_PORT", "5000"))
BASE = f"http://{HOST}:{PORT}"
SKIP_SERVER = os.getenv("FLOWSTUDIO_SKIP_SERVER", "").lower() in ("1", "true", "yes")

# Negative test mode: expect server startup to fail
EXPECT_STARTUP_FAIL = os.getenv("FLOWSTUDIO_EXPECT_STARTUP_FAIL", "").lower() in (
    "1",
    "true",
    "yes",
)
# File to hide for negative test (e.g., "main.js")
HIDE_UI_ENTRYPOINT = os.getenv("FLOWSTUDIO_HIDE_UI_ENTRYPOINT", "")

# Path to JS directory for hiding entrypoints (relative to script, not cwd)
SCRIPT_DIR = Path(__file__).resolve().parent
JS_DIR = SCRIPT_DIR / "flow_studio_ui" / "js"

# Endpoints to test: (method, path, description, timeout_s)
ENDPOINTS = [
    ("GET", "/", "UI HTML", 10.0),
    ("GET", "/openapi.json", "OpenAPI schema", 10.0),
    ("GET", "/api/flows", "Flow definitions", 10.0),
    ("GET", "/api/runs?limit=25&offset=0", "Runs list (paginated)", 15.0),
    ("GET", "/api/agents", "Agent definitions", 10.0),
    ("GET", "/platform/status", "Platform status", 60.0),  # Can be slow first call
    ("POST", "/platform/status/refresh", "Status refresh", 60.0),
    ("POST", "/api/reload", "Reload config", 15.0),
]


def http(method: str, path: str, timeout: float = 30.0) -> tuple[int, bytes, float]:
    """Make HTTP request, return (status_code, body, elapsed_ms)."""
    req = Request(BASE + path, method=method)
    t0 = time.perf_counter()
    try:
        with urlopen(req, timeout=timeout) as r:
            body = r.read()
            elapsed = (time.perf_counter() - t0) * 1000.0
            return r.status, body, elapsed
    except HTTPError as e:
        elapsed = (time.perf_counter() - t0) * 1000.0
        return e.code, e.read() if e.fp else b"", elapsed
    except URLError as e:
        elapsed = (time.perf_counter() - t0) * 1000.0
        return 0, str(e).encode("utf-8", "replace"), elapsed
    except TimeoutError:
        elapsed = (time.perf_counter() - t0) * 1000.0
        return 0, b"TIMEOUT", elapsed


def wait_up(deadline_s: float = 20.0) -> bool:
    """Wait for server to become ready."""
    t0 = time.time()
    while time.time() - t0 < deadline_s:
        code, _, _ = http("GET", "/openapi.json", timeout=2.0)
        if code == 200:
            return True
        time.sleep(0.25)
    return False


def get_env_info() -> dict:
    """Collect environment information."""
    import platform

    # Get git SHA if available
    git_sha = "unknown"
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            git_sha = result.stdout.strip()[:12]
    except Exception:
        pass

    # Get Python version
    python_version = platform.python_version()

    # Get uv version if available
    uv_version = "unknown"
    try:
        result = subprocess.run(
            ["uv", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            uv_version = result.stdout.strip()
    except Exception:
        pass

    # Compute effective TTL (mirrors logic in status_provider.py)
    # Defensive parsing: don't crash if env var is malformed
    ttl_env = os.getenv("FLOW_STUDIO_STATUS_TTL_SECONDS", "")
    ttl_parse_error = None
    try:
        effective_ttl = int(ttl_env) if ttl_env else 300  # Default: 5 min
    except ValueError:
        effective_ttl = 300
        ttl_parse_error = ttl_env

    env_info = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host": HOST,
        "port": PORT,
        "base_url": BASE,
        "git_sha": git_sha,
        "python_version": python_version,
        "uv_version": uv_version,
        "platform": platform.platform(),
        "ttl_env_raw": ttl_env,
        "ttl_effective_seconds": effective_ttl,
        "env_vars": {
            "FLOW_STUDIO_STRICT_UI_ASSETS": os.getenv("FLOW_STUDIO_STRICT_UI_ASSETS", ""),
            "FLOW_STUDIO_STATUS_TTL_SECONDS": ttl_env,
            "FLOWSTUDIO_SKIP_SERVER": os.getenv("FLOWSTUDIO_SKIP_SERVER", ""),
            "FLOWSTUDIO_EXPECT_STARTUP_FAIL": os.getenv("FLOWSTUDIO_EXPECT_STARTUP_FAIL", ""),
            "FLOWSTUDIO_HIDE_UI_ENTRYPOINT": os.getenv("FLOWSTUDIO_HIDE_UI_ENTRYPOINT", ""),
        },
    }
    if ttl_parse_error:
        env_info["ttl_parse_error"] = ttl_parse_error
    return env_info


def run_negative_test(
    log_path: Path, env_info: dict, summary_path: Path, results_path: Path
) -> int:
    """
    Run negative test: verify server FAILS startup when entrypoint is hidden.

    Returns 0 if server failed as expected, 1 if it unexpectedly started.
    Writes both summary.txt (human-readable) and results.json (machine-readable).
    """
    hidden_file = JS_DIR / HIDE_UI_ENTRYPOINT
    backup_file = JS_DIR / f"{HIDE_UI_ENTRYPOINT}.bak"

    if not hidden_file.exists():
        print(f"ERROR: Entrypoint to hide does not exist: {hidden_file}")
        return 1

    # Hide the entrypoint
    print(f"Hiding entrypoint: {hidden_file} -> {backup_file}")
    hidden_file.rename(backup_file)

    try:
        # Start server (expect it to fail)
        cmd = [
            "uv",
            "run",
            "uvicorn",
            "swarm.tools.flow_studio_fastapi:app",
            "--host",
            HOST,
            "--port",
            str(PORT),
            "--log-level",
            "info",
        ]
        print(f"Starting server (expecting failure): {' '.join(cmd)}")

        with log_path.open("wb") as log:
            proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)

        # Wait for server to exit (should fail quickly)
        try:
            exit_code = proc.wait(timeout=15.0)
        except subprocess.TimeoutExpired:
            # Server didn't exit - it started successfully, which is a test failure
            print("ERROR: Server started successfully when it should have failed!")
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

            summary_lines = [
                "Flow Studio Strict Negative Test Results",
                "=" * 40,
                "",
                f"Timestamp: {env_info['timestamp']}",
                f"Git SHA: {env_info['git_sha']}",
                f"Hidden entrypoint: {HIDE_UI_ENTRYPOINT}",
                "",
                "FAILED: Server started successfully when it should have failed",
                "The strict mode did not prevent startup with missing entrypoint.",
            ]
            summary_path.write_text("\n".join(summary_lines), encoding="utf-8")
            results_path.write_text(
                json.dumps(
                    {
                        "mode": "strict-negative",
                        "hidden_file": HIDE_UI_ENTRYPOINT,
                        "exit_code": None,
                        "passed": False,
                        "failure_reason": "server_started_unexpectedly",
                        "pattern_matched": False,
                        "timestamp": env_info["timestamp"],
                        "git_sha": env_info["git_sha"],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            return 1

        # Server exited - check if it failed as expected
        log_content = log_path.read_text(encoding="utf-8", errors="replace")

        # Expected error patterns from flow_studio_fastapi.py
        expected_patterns = [
            "Missing Flow Studio entrypoints",
            "Missing compiled Flow Studio module dependencies",
        ]

        found_expected = any(p in log_content for p in expected_patterns)

        if exit_code != 0 and found_expected:
            print(f"✅ Server failed as expected (exit code {exit_code})")
            summary_lines = [
                "Flow Studio Strict Negative Test Results",
                "=" * 40,
                "",
                f"Timestamp: {env_info['timestamp']}",
                f"Git SHA: {env_info['git_sha']}",
                f"Hidden entrypoint: {HIDE_UI_ENTRYPOINT}",
                "",
                f"PASSED: Server failed as expected (exit code {exit_code})",
                "Strict mode correctly prevented startup with missing entrypoint.",
            ]
            summary_path.write_text("\n".join(summary_lines), encoding="utf-8")
            results_path.write_text(
                json.dumps(
                    {
                        "mode": "strict-negative",
                        "hidden_file": HIDE_UI_ENTRYPOINT,
                        "exit_code": exit_code,
                        "passed": True,
                        "failure_reason": None,
                        "pattern_matched": True,
                        "timestamp": env_info["timestamp"],
                        "git_sha": env_info["git_sha"],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            return 0
        else:
            print(f"ERROR: Server exited (code {exit_code}) but didn't show expected error")
            print(f"       Expected one of: {expected_patterns}")
            summary_lines = [
                "Flow Studio Strict Negative Test Results",
                "=" * 40,
                "",
                f"Timestamp: {env_info['timestamp']}",
                f"Git SHA: {env_info['git_sha']}",
                f"Hidden entrypoint: {HIDE_UI_ENTRYPOINT}",
                "",
                f"FAILED: Server exited (code {exit_code}) but wrong error",
                f"Expected one of: {expected_patterns}",
                "Log content may indicate a different failure mode.",
            ]
            summary_path.write_text("\n".join(summary_lines), encoding="utf-8")
            results_path.write_text(
                json.dumps(
                    {
                        "mode": "strict-negative",
                        "hidden_file": HIDE_UI_ENTRYPOINT,
                        "exit_code": exit_code,
                        "passed": False,
                        "failure_reason": "wrong_error_pattern",
                        "pattern_matched": False,
                        "expected_patterns": expected_patterns,
                        "timestamp": env_info["timestamp"],
                        "git_sha": env_info["git_sha"],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            return 1

    finally:
        # Always restore the hidden file
        if backup_file.exists():
            print(f"Restoring entrypoint: {backup_file} -> {hidden_file}")
            backup_file.rename(hidden_file)


def main() -> int:
    ART_DIR.mkdir(parents=True, exist_ok=True)
    req_dir = ART_DIR / "requests"
    req_dir.mkdir(parents=True, exist_ok=True)

    log_path = ART_DIR / "server.log"
    env_path = ART_DIR / "env.json"
    results_path = ART_DIR / "results.json"
    timings_path = ART_DIR / "timings.json"
    summary_path = ART_DIR / "summary.txt"

    # Write environment info
    env_info = get_env_info()
    env_path.write_text(json.dumps(env_info, indent=2), encoding="utf-8")

    # Negative test mode: verify server fails when entrypoint is hidden
    if EXPECT_STARTUP_FAIL:
        if not HIDE_UI_ENTRYPOINT:
            print("ERROR: FLOWSTUDIO_EXPECT_STARTUP_FAIL requires FLOWSTUDIO_HIDE_UI_ENTRYPOINT")
            return 1
        if SKIP_SERVER:
            print("ERROR: Cannot run negative test with FLOWSTUDIO_SKIP_SERVER")
            return 1
        result = run_negative_test(log_path, env_info, summary_path, results_path)
        print(f"   Artifacts: {ART_DIR}")
        return result

    proc = None

    if not SKIP_SERVER:
        # Start server
        cmd = [
            "uv",
            "run",
            "uvicorn",
            "swarm.tools.flow_studio_fastapi:app",
            "--host",
            HOST,
            "--port",
            str(PORT),
            "--log-level",
            "info",
        ]
        print(f"Starting server: {' '.join(cmd)}")
        with log_path.open("wb") as log:
            proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
    else:
        print(f"Using existing server at {BASE}")
        log_path.write_text("(using existing server, no logs captured)", encoding="utf-8")

    try:
        # Wait for server
        print("Waiting for server to be ready...")
        if not wait_up(deadline_s=30.0):
            print("ERROR: Server did not become ready (GET /openapi.json never returned 200)")
            return 1

        print(f"Server ready at {BASE}")
        print(f"Testing {len(ENDPOINTS)} endpoints...")
        print()

        results = []
        timings = []
        all_passed = True

        for method, path, desc, timeout in ENDPOINTS:
            code, body, elapsed_ms = http(method, path, timeout=timeout)

            # Determine pass/fail
            # 200-299 is success, 404 is acceptable for some endpoints
            passed = 200 <= code < 300

            status_icon = "[OK]" if passed else "[FAIL]"
            print(f"  {status_icon} {method} {path}: {code} ({elapsed_ms:.0f}ms)")

            if not passed:
                all_passed = False

            result = {
                "method": method,
                "path": path,
                "description": desc,
                "status": code,
                "ms": round(elapsed_ms, 2),
                "bytes": len(body),
                "passed": passed,
            }
            results.append(result)
            timings.append({"path": path, "ms": elapsed_ms})

            # Save individual request artifacts
            safe_name = (
                path.strip("/").replace("/", "_").replace("?", "_").replace("&", "_") or "root"
            )
            (req_dir / f"{method}_{safe_name}.meta.json").write_text(
                json.dumps(result, indent=2), encoding="utf-8"
            )
            (req_dir / f"{method}_{safe_name}.body").write_bytes(body[:2_000_000])  # Cap at 2MB

        # Write aggregate results
        results_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        timings_path.write_text(json.dumps(timings, indent=2), encoding="utf-8")

        # Compute summary stats
        total = len(results)
        passed_count = sum(1 for r in results if r["passed"])
        failed_count = total - passed_count
        avg_ms = sum(r["ms"] for r in results) / total if total else 0
        max_ms = max(r["ms"] for r in results) if results else 0

        summary_lines = [
            "Flow Studio Smoke Test Results",
            "=" * 40,
            "",
            f"Timestamp: {env_info['timestamp']}",
            f"Git SHA: {env_info['git_sha']}",
            f"Base URL: {BASE}",
            "",
            f"Total endpoints: {total}",
            f"Passed: {passed_count}",
            f"Failed: {failed_count}",
            "",
            f"Avg latency: {avg_ms:.0f}ms",
            f"Max latency: {max_ms:.0f}ms",
            "",
            "Endpoint Results:",
            "-" * 40,
        ]
        for r in results:
            icon = "[OK]" if r["passed"] else "[FAIL]"
            summary_lines.append(
                f"  {icon} {r['method']} {r['path']}: {r['status']} ({r['ms']:.0f}ms)"
            )

        summary_path.write_text("\n".join(summary_lines), encoding="utf-8")

        print()
        if all_passed:
            print(f"[PASS] Flow Studio smoke PASSED ({passed_count}/{total} endpoints)")
        else:
            print(f"[FAIL] Flow Studio smoke FAILED ({failed_count}/{total} endpoints failed)")

        print(f"   Artifacts: {ART_DIR}")
        return 0 if all_passed else 1

    finally:
        # Stop server if we started it
        if proc is not None and proc.poll() is None:
            print("Stopping server...")
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
