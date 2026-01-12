#!/usr/bin/env python3
"""
Selftest Incident Pack Generator

Collects diagnostic artifacts for troubleshooting selftest failures.

Creates a tarball containing:
- Full selftest run output (JSON v2 format)
- /api/selftest/plan response
- /platform/status response
- Degradation log
- Recent commits and CI logs
- Environment information

Usage:
    python selftest_incident_pack.py [--output-dir DIR]
    make selftest-incident-pack

Output:
    selftest_incident_<timestamp>.tar.gz
"""

import argparse
import json
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


class IncidentPackCollector:
    """Collects diagnostic artifacts for selftest incidents."""

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or Path.cwd()
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.pack_name = f"selftest_incident_{self.timestamp}"
        self.temp_dir: Optional[Path] = None
        self.artifacts: Dict[str, Any] = {}
        self.errors: list[str] = []

    def collect(self) -> Path:
        """Collect all artifacts and create tarball."""
        print(f"Collecting incident pack: {self.pack_name}")
        print("=" * 60)

        # Create temporary directory
        self.temp_dir = Path(tempfile.mkdtemp(prefix="selftest_incident_"))
        pack_dir = self.temp_dir / self.pack_name
        pack_dir.mkdir()

        # Collect all artifacts
        steps = [
            ("Selftest output", self._collect_selftest_output),
            ("Selftest plan", self._collect_selftest_plan),
            ("Platform status", self._collect_platform_status),
            ("Degradation log", self._collect_degradation_log),
            ("Recent commits", self._collect_recent_commits),
            ("CI logs", self._collect_ci_logs),
            ("Environment info", self._collect_environment),
        ]

        for step_name, step_func in steps:
            print(f"\n[{step_name}]")
            try:
                step_func(pack_dir)
                print("  [OK] Collected")
            except Exception as e:
                error_msg = f"{step_name}: {str(e)}"
                self.errors.append(error_msg)
                print(f"  [FAIL] Failed: {e}")

        # Write manifest
        self._write_manifest(pack_dir)

        # Write README
        self._write_readme(pack_dir)

        # Create tarball
        tarball_path = self._create_tarball(pack_dir)

        # Cleanup
        self._cleanup()

        return tarball_path

    def _collect_selftest_output(self, pack_dir: Path) -> None:
        """Run selftest and capture JSON v2 output."""
        repo_root = self._get_repo_root()
        selftest_script = repo_root / "swarm" / "tools" / "selftest.py"

        result = subprocess.run(
            ["uv", "run", str(selftest_script), "--json-v2"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )

        # Save output even if selftest failed (that's why we're here!)
        output_file = pack_dir / "selftest_output.json"

        if result.stdout:
            try:
                # Validate JSON
                data = json.loads(result.stdout)
                with open(output_file, "w") as f:
                    json.dump(data, f, indent=2)
                self.artifacts["selftest_output"] = {
                    "file": "selftest_output.json",
                    "status": "captured",
                    "exit_code": result.returncode,
                }
            except json.JSONDecodeError as e:
                # Save raw output if JSON parsing fails
                with open(output_file, "w") as f:
                    f.write(result.stdout)
                self.artifacts["selftest_output"] = {
                    "file": "selftest_output.json",
                    "status": "raw_output",
                    "parse_error": str(e),
                    "exit_code": result.returncode,
                }
        else:
            # Save stderr if stdout is empty
            error_file = pack_dir / "selftest_error.txt"
            with open(error_file, "w") as f:
                f.write(result.stderr)
            self.artifacts["selftest_output"] = {
                "file": "selftest_error.txt",
                "status": "error",
                "exit_code": result.returncode,
            }

    def _collect_selftest_plan(self, pack_dir: Path) -> None:
        """Fetch /api/selftest/plan response."""
        try:
            response = urllib.request.urlopen(
                "http://localhost:5000/api/selftest/plan",
                timeout=10,
            )
            data = json.loads(response.read().decode())

            output_file = pack_dir / "selftest_plan.json"
            with open(output_file, "w") as f:
                json.dump(data, f, indent=2)

            self.artifacts["selftest_plan"] = {
                "file": "selftest_plan.json",
                "status": "captured",
            }
        except urllib.error.URLError as e:
            # API not running; save error
            error_file = pack_dir / "selftest_plan_error.txt"
            with open(error_file, "w") as f:
                f.write("Failed to connect to http://localhost:5000/api/selftest/plan\n")
                f.write(f"Error: {str(e)}\n")
                f.write("\nNote: Flow Studio may not be running. Start with: make flow-studio\n")

            self.artifacts["selftest_plan"] = {
                "file": "selftest_plan_error.txt",
                "status": "unavailable",
                "error": str(e),
            }

    def _collect_platform_status(self, pack_dir: Path) -> None:
        """Fetch /platform/status response."""
        try:
            response = urllib.request.urlopen(
                "http://localhost:5000/platform/status",
                timeout=10,
            )
            data = json.loads(response.read().decode())

            output_file = pack_dir / "platform_status.json"
            with open(output_file, "w") as f:
                json.dump(data, f, indent=2)

            self.artifacts["platform_status"] = {
                "file": "platform_status.json",
                "status": "captured",
            }
        except urllib.error.URLError as e:
            error_file = pack_dir / "platform_status_error.txt"
            with open(error_file, "w") as f:
                f.write("Failed to connect to http://localhost:5000/platform/status\n")
                f.write(f"Error: {str(e)}\n")

            self.artifacts["platform_status"] = {
                "file": "platform_status_error.txt",
                "status": "unavailable",
                "error": str(e),
            }

    def _collect_degradation_log(self, pack_dir: Path) -> None:
        """Fetch degradation log from API."""
        try:
            response = urllib.request.urlopen(
                "http://localhost:5000/platform/degradation-log",
                timeout=10,
            )
            data = json.loads(response.read().decode())

            output_file = pack_dir / "degradation_log.json"
            with open(output_file, "w") as f:
                json.dump(data, f, indent=2)

            self.artifacts["degradation_log"] = {
                "file": "degradation_log.json",
                "status": "captured",
                "entries": len(data.get("entries", [])),
            }
        except urllib.error.URLError as e:
            error_file = pack_dir / "degradation_log_error.txt"
            with open(error_file, "w") as f:
                f.write("Failed to connect to http://localhost:5000/platform/degradation-log\n")
                f.write(f"Error: {str(e)}\n")

            self.artifacts["degradation_log"] = {
                "file": "degradation_log_error.txt",
                "status": "unavailable",
                "error": str(e),
            }

    def _collect_recent_commits(self, pack_dir: Path) -> None:
        """Collect recent git commit history."""
        repo_root = self._get_repo_root()

        # Last 10 commits (oneline)
        result = subprocess.run(
            ["git", "log", "-10", "--oneline"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
        )

        output_file = pack_dir / "recent_commits.txt"
        with open(output_file, "w") as f:
            f.write("=== Last 10 Commits ===\n\n")
            f.write(result.stdout)

        # Current git status
        result = subprocess.run(
            ["git", "status"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
        )

        with open(output_file, "a") as f:
            f.write("\n\n=== Git Status ===\n\n")
            f.write(result.stdout)

        self.artifacts["recent_commits"] = {
            "file": "recent_commits.txt",
            "status": "captured",
        }

    def _collect_ci_logs(self, pack_dir: Path) -> None:
        """Collect recent CI workflow logs (if available via gh CLI)."""
        ci_dir = pack_dir / "ci_logs"
        ci_dir.mkdir()

        try:
            # Check if gh CLI is available
            subprocess.run(
                ["gh", "--version"],
                capture_output=True,
                check=True,
                timeout=5,
            )

            # Get latest workflow run
            result = subprocess.run(
                ["gh", "run", "list", "--limit", "5", "--json", "databaseId,status,conclusion,name"],
                cwd=self._get_repo_root(),
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                runs = json.loads(result.stdout)

                # Save run list
                with open(ci_dir / "recent_runs.json", "w") as f:
                    json.dump(runs, f, indent=2)

                # Try to download logs for latest run
                if runs:
                    latest_run_id = runs[0]["databaseId"]
                    log_result = subprocess.run(
                        ["gh", "run", "view", str(latest_run_id), "--log"],
                        cwd=self._get_repo_root(),
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )

                    if log_result.returncode == 0:
                        with open(ci_dir / "latest_run.log", "w") as f:
                            f.write(log_result.stdout)

                self.artifacts["ci_logs"] = {
                    "directory": "ci_logs/",
                    "status": "captured",
                    "runs_found": len(runs),
                }
            else:
                raise subprocess.CalledProcessError(result.returncode, "gh run list")

        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            # gh CLI not available or command failed
            error_file = ci_dir / "ci_logs_error.txt"
            with open(error_file, "w") as f:
                f.write("Failed to collect CI logs\n")
                f.write(f"Error: {str(e)}\n")
                f.write("\nNote: Install gh CLI or check repository authentication\n")

            self.artifacts["ci_logs"] = {
                "directory": "ci_logs/",
                "status": "unavailable",
                "error": str(e),
            }

    def _collect_environment(self, pack_dir: Path) -> None:
        """Collect environment information."""
        output_file = pack_dir / "environment.txt"

        with open(output_file, "w") as f:
            f.write("=== Environment Information ===\n\n")

            # Python version
            result = subprocess.run(
                ["python", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            f.write(f"Python: {result.stdout.strip()}\n")

            # uv version
            result = subprocess.run(
                ["uv", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            f.write(f"uv: {result.stdout.strip()}\n")

            # OS info
            result = subprocess.run(
                ["uname", "-a"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            f.write(f"\nOS: {result.stdout.strip()}\n")

            # Git branch
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self._get_repo_root(),
                capture_output=True,
                text=True,
                timeout=5,
            )
            f.write(f"\nGit Branch: {result.stdout.strip()}\n")

            # Git commit
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self._get_repo_root(),
                capture_output=True,
                text=True,
                timeout=5,
            )
            f.write(f"Git Commit: {result.stdout.strip()}\n")

            # Disk space
            result = subprocess.run(
                ["df", "-h", "."],
                cwd=self._get_repo_root(),
                capture_output=True,
                text=True,
                timeout=5,
            )
            f.write(f"\n=== Disk Space ===\n\n{result.stdout}\n")

        self.artifacts["environment"] = {
            "file": "environment.txt",
            "status": "captured",
        }

    def _write_manifest(self, pack_dir: Path) -> None:
        """Write manifest.json with metadata and artifact index."""
        manifest = {
            "incident_pack_version": "1.0",
            "generated_at": datetime.now().isoformat(),
            "timestamp": self.timestamp,
            "artifacts": self.artifacts,
            "collection_errors": self.errors,
            "total_artifacts": len(self.artifacts),
            "total_errors": len(self.errors),
        }

        output_file = pack_dir / "manifest.json"
        with open(output_file, "w") as f:
            json.dump(manifest, f, indent=2)

    def _write_readme(self, pack_dir: Path) -> None:
        """Write README.txt explaining pack contents."""
        output_file = pack_dir / "README.txt"

        with open(output_file, "w") as f:
            f.write("=" * 60 + "\n")
            f.write("Selftest Incident Pack\n")
            f.write("=" * 60 + "\n\n")

            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Pack Name: {self.pack_name}\n\n")

            f.write("This diagnostic bundle contains artifacts for troubleshooting\n")
            f.write("selftest failures. Attach this to PagerDuty incidents or\n")
            f.write("GitHub issues.\n\n")

            f.write("=" * 60 + "\n")
            f.write("Contents\n")
            f.write("=" * 60 + "\n\n")

            f.write("manifest.json          - Index of all artifacts\n")
            f.write("README.txt             - This file\n")
            f.write("selftest_output.json   - Full selftest run (JSON v2)\n")
            f.write("selftest_plan.json     - /api/selftest/plan response\n")
            f.write("platform_status.json   - /platform/status response\n")
            f.write("degradation_log.json   - Current degradation log\n")
            f.write("recent_commits.txt     - Last 10 commits + git status\n")
            f.write("ci_logs/               - Recent CI workflow logs\n")
            f.write("environment.txt        - Python, uv, OS, git info\n\n")

            if self.errors:
                f.write("=" * 60 + "\n")
                f.write("Collection Errors\n")
                f.write("=" * 60 + "\n\n")
                for error in self.errors:
                    f.write(f"  - {error}\n")
                f.write("\n")

            f.write("=" * 60 + "\n")
            f.write("Next Steps\n")
            f.write("=" * 60 + "\n\n")

            f.write("1. Review selftest_output.json for failure details\n")
            f.write("2. Check degradation_log.json for known degradations\n")
            f.write("3. Review recent_commits.txt for potential causes\n")
            f.write("4. Follow runbooks referenced in alert messages\n")
            f.write("5. Document findings in incident postmortem\n\n")

            f.write("=" * 60 + "\n")
            f.write("References\n")
            f.write("=" * 60 + "\n\n")

            f.write("- Selftest Docs: swarm/SELFTEST_SYSTEM.md\n")
            f.write("- Alert Policies: observability/alerts/selftest_alerts.yaml\n")
            f.write("- SLO Definitions: observability/slos/selftest_slos.yaml\n")
            f.write("- Runbooks: docs/runbooks/\n")

    def _create_tarball(self, pack_dir: Path) -> Path:
        """Create compressed tarball of incident pack."""
        tarball_path = self.output_dir / f"{self.pack_name}.tar.gz"

        print(f"\nCreating tarball: {tarball_path}")

        with tarfile.open(tarball_path, "w:gz") as tar:
            tar.add(pack_dir, arcname=self.pack_name)

        # Print size
        size_mb = tarball_path.stat().st_size / (1024 * 1024)
        print(f"Tarball size: {size_mb:.2f} MB")

        return tarball_path

    def _cleanup(self) -> None:
        """Remove temporary directory."""
        if self.temp_dir and self.temp_dir.exists():
            import shutil
            shutil.rmtree(self.temp_dir)

    def _get_repo_root(self) -> Path:
        """Get repository root directory."""
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return Path(result.stdout.strip())


def main():
    parser = argparse.ArgumentParser(
        description="Generate selftest incident pack for troubleshooting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python selftest_incident_pack.py
  python selftest_incident_pack.py --output-dir /tmp
  make selftest-incident-pack

Output:
  Creates selftest_incident_<timestamp>.tar.gz
        """,
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.cwd(),
        help="Directory to write tarball (default: current directory)",
    )

    args = parser.parse_args()

    try:
        collector = IncidentPackCollector(output_dir=args.output_dir)
        tarball_path = collector.collect()

        print("\n" + "=" * 60)
        print("Incident pack created successfully!")
        print("=" * 60)
        print(f"\nLocation: {tarball_path}")
        print("\nNext steps:")
        print("  1. Attach to PagerDuty incident or GitHub issue")
        print("  2. Review artifacts inside the tarball")
        print("  3. Follow runbook guidance from alert message")
        print()

        return 0

    except Exception as e:
        print(f"\n[FAIL] Error creating incident pack: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
