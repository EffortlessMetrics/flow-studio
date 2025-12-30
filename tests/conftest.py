"""
Test fixtures and utilities for swarm validator tests.

This module provides reusable fixtures for testing the swarm alignment validator,
including temporary repositories, agent files, and helper functions.
"""

# Filter gherkin deprecation warning before any imports trigger it
import warnings
warnings.filterwarnings(
    "ignore",
    message="'maxsplit' is passed as positional argument",
    category=DeprecationWarning,
)

import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

# ============================================================================
# BDD Step Definitions (for pytest-bdd)
# ============================================================================
# Import pytest-bdd decorators and steps for step definitions
# All actual step definitions are in tests/bdd/steps/selftest_steps.py
# We import that module here to make them available to all tests
import json
import subprocess
import sys
from pathlib import Path as _Path
from pytest_bdd import given, parsers, then, when

# Import BDD step definitions from tests/bdd/steps/ to make them available
# to all tests (including tests/test_selftest_bdd.py)
# We need to add both the tests directory and repo root to sys.path for imports to work
_tests_dir = _Path(__file__).parent
_repo_root = _tests_dir.parent
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

# Now import all BDD step definitions explicitly
# This is required for pytest-bdd to discover them
try:
    from bdd.steps.selftest_steps import *  # noqa: F401, F403
except ImportError as e:
    # If this fails, something is wrong with the test setup
    import warnings
    warnings.warn(f"Could not import BDD step definitions: {e}")

# ============================================================================
# Temporary Repository Fixtures
# ============================================================================


@pytest.fixture
def temp_repo(tmp_path):
    """
    Create a temporary repository with minimal valid structure.

    Returns a Path to the temporary directory with:
    - swarm/AGENTS.md (empty but valid)
    - .claude/agents/ (empty directory)
    - .claude/skills/ (empty directory)
    - swarm/flows/ (empty directory)
    - swarm/tools/validate_swarm.py (copied from real repo)
    """
    repo = tmp_path / "test_repo"
    repo.mkdir()

    # Create directory structure
    (repo / "swarm").mkdir()
    (repo / "swarm" / "tools").mkdir()
    (repo / ".claude" / "agents").mkdir(parents=True)
    (repo / ".claude" / "skills").mkdir(parents=True)
    (repo / "swarm" / "flows").mkdir(parents=True)

    # Create empty AGENTS.md
    (repo / "swarm" / "AGENTS.md").write_text("# Agent Registry\n\n")

    # Copy validator script from real repo
    real_validator = Path(__file__).parent.parent / "swarm" / "tools" / "validate_swarm.py"
    if real_validator.exists():
        shutil.copy(real_validator, repo / "swarm" / "tools" / "validate_swarm.py")

    # Copy swarm/__init__.py for package structure
    real_init = Path(__file__).parent.parent / "swarm" / "__init__.py"
    if real_init.exists():
        shutil.copy(real_init, repo / "swarm" / "__init__.py")

    # Copy swarm/validator module (required by validate_swarm.py)
    real_validator_module = Path(__file__).parent.parent / "swarm" / "validator"
    if real_validator_module.exists():
        (repo / "swarm" / "validator").mkdir(parents=True, exist_ok=True)
        for file in real_validator_module.glob("*.py"):
            shutil.copy(file, repo / "swarm" / "validator" / file.name)

    return repo


@pytest.fixture
def valid_repo(temp_repo):
    """
    Create a temporary repository with 3 valid agents.

    Returns a Path to the temporary directory with:
    - swarm/AGENTS.md with 3 agent entries
    - .claude/agents/test-agent-1.md (valid frontmatter)
    - .claude/agents/test-agent-2.md (valid frontmatter)
    - .claude/agents/test-agent-3.md (valid frontmatter)
    """
    # Add agents to registry (pipe table format like real AGENTS.md)
    agents_md = temp_repo / "swarm" / "AGENTS.md"
    agents_md.write_text("""# Agent Registry

| Key | Flows | Role Family | Color | Source | Short Role |
|-----|-------|-------------|-------|--------|------------|
| test-agent-1 | 1 | implementation | green | project/user | First test agent for validation |
| test-agent-2 | 1 | implementation | green | project/user | Second test agent for validation |
| test-agent-3 | 1,2 | implementation | green | project/user | Third test agent for validation |
""")

    # Create agent files
    for i in range(1, 4):
        agent_file = temp_repo / ".claude" / "agents" / f"test-agent-{i}.md"
        agent_file.write_text(f"""---
name: test-agent-{i}
description: Test agent {i} for validation
color: green
model: inherit
---

You are test agent {i}.
""")

    return temp_repo


# ============================================================================
# Agent File Fixtures
# ============================================================================


def create_agent_file(repo_path: Path, agent_name: str, frontmatter: Optional[Dict] = None, prompt: str = ""):
    """
    Create an agent file with specified frontmatter.

    Args:
        repo_path: Path to repository root
        agent_name: Agent key name (without .md extension)
        frontmatter: Dictionary of frontmatter fields (if None, creates valid minimal frontmatter)
        prompt: Agent prompt text (after frontmatter)
    """
    if frontmatter is None:
        frontmatter = {
            "name": agent_name,
            "description": f"Test agent {agent_name}",
            "color": "green",
            "model": "inherit"
        }

    agent_path = repo_path / ".claude" / "agents" / f"{agent_name}.md"

    # Build frontmatter YAML
    yaml_lines = ["---"]
    for key, value in frontmatter.items():
        if isinstance(value, list):
            yaml_lines.append(f"{key}: [{', '.join(value)}]")
        elif isinstance(value, str):
            yaml_lines.append(f"{key}: {value}")
        else:
            yaml_lines.append(f"{key}: {value}")
    yaml_lines.append("---")

    content = "\n".join(yaml_lines) + "\n\n" + (prompt or f"You are {agent_name}.")
    agent_path.write_text(content)


def create_agent_with_invalid_yaml(repo_path: Path, agent_name: str, yaml_error: str):
    """
    Create an agent file with intentionally invalid YAML.

    Args:
        repo_path: Path to repository root
        agent_name: Agent key name
        yaml_error: Type of error ('unclosed_quote', 'invalid_indent', 'missing_delimiter')
    """
    agent_path = repo_path / ".claude" / "agents" / f"{agent_name}.md"

    if yaml_error == "unclosed_quote":
        content = """---
name: test-agent
description: "This quote is not closed
model: inherit
---

Agent prompt.
"""
    elif yaml_error == "invalid_indent":
        content = """---
name: test-agent
description: Valid description
  model: inherit
---

Agent prompt.
"""
    elif yaml_error == "missing_delimiter":
        content = """---
name: test-agent
description: Valid description
model: inherit

Agent prompt without closing ---.
"""
    else:
        raise ValueError(f"Unknown yaml_error type: {yaml_error}")

    agent_path.write_text(content)


# ============================================================================
# Registry Fixtures
# ============================================================================


def add_agent_to_registry(repo_path: Path, agent_key: str, line_hint: Optional[int] = None, role_family: Optional[str] = None):
    """
    Add an agent entry to swarm/AGENTS.md pipe table.

    Args:
        repo_path: Path to repository root
        agent_key: Agent key to add
        line_hint: Optional line number comment (for testing error messages)
        role_family: Optional role family (shaping, spec, design, implementation, critic, verification, analytics, reporter, infra)
    """
    agents_md = repo_path / "swarm" / "AGENTS.md"
    existing = agents_md.read_text()
    role_fam = role_family or "implementation"

    # Map role family to canonical color
    role_family_color_map = {
        "shaping": "yellow",
        "spec": "purple",
        "design": "purple",
        "implementation": "green",
        "critic": "red",
        "verification": "blue",
        "analytics": "orange",
        "reporter": "pink",
        "infra": "cyan",
    }
    color = role_family_color_map.get(role_fam, "green")

    # Determine table format based on existing content
    if "| Key |" not in existing:
        # Create new table with Role Family column
        table_header = """
| Key | Flows | Role Family | Color | Source | Short Role |
|-----|-------|-------------|-------|--------|------------|
"""
        new_entry = table_header + f"| {agent_key} | 1 | {role_fam} | {color} | project/user | Test agent {agent_key} |\n"
        agents_md.write_text(existing + new_entry)
    else:
        # Check the current table format
        if "Role Family" in existing:
            # Already has Role Family column - use it
            if "| Color |" in existing:
                # Has both Role Family and Color - modern format
                new_entry = f"| {agent_key} | 1 | {role_fam} | {color} | project/user | Test agent {agent_key} |\n"
            else:
                # Has Role Family but no Color - add Color column
                new_entry = f"| {agent_key} | 1 | {role_fam} | project/user | Test agent {agent_key} |\n"
        else:
            # Old format: Key | Flows | Category | Source | Short Role
            # Just append without Role Family and Color
            new_entry = f"| {agent_key} | 1 | implementation | project/user | Test agent {agent_key} |\n"

        agents_md.write_text(existing + new_entry)


# ============================================================================
# Validation Runner Fixtures
# ============================================================================


@pytest.fixture
def run_validator():
    """
    Fixture that returns a function to run the validator on a given repo path.

    Returns:
        Function(repo_path, flags=[]) -> CompletedProcess
    """
    def _run(repo_path: Path, flags: Optional[List[str]] = None):
        """
        Run the validator on the given repository.

        Args:
            repo_path: Path to repository root
            flags: Optional list of command-line flags

        Returns:
            subprocess.CompletedProcess with returncode, stdout, stderr
        """
        if flags is None:
            flags = []

        cmd = ["uv", "run", "swarm/tools/validate_swarm.py"] + flags

        result = subprocess.run(
            cmd,
            cwd=repo_path,
            capture_output=True,
            text=True
        )

        return result

    return _run


def parse_errors(stderr: str) -> List[Dict[str, str]]:
    """
    Parse error messages from validator stderr output.

    Format: [FAIL] TYPE: location problem
            Fix: action

    Args:
        stderr: Validator stderr output

    Returns:
        List of error dictionaries with keys: type, location, message, fix
    """
    errors = []
    lines = stderr.strip().split("\n")

    current_error = None
    for line in lines:
        line = line.strip()
        if line.startswith("[FAIL]") or line.startswith("[WARN]"):
            # New error or warning
            if current_error:
                errors.append(current_error)

            # Parse error line: [FAIL] TYPE: location problem
            # Split only on first colon to get TYPE
            first_colon = line.find(":")
            if first_colon > 0:
                error_type = line[6:first_colon].strip()  # Skip [FAIL] or [WARN]
                rest = line[first_colon+1:].strip()

                # Rest contains "location problem"
                # Location can be file:line or just file
                current_error = {
                    "type": error_type,
                    "location": "",  # Will be extracted from rest if needed
                    "message": rest,  # Full message including location
                    "fix": ""
                }
        elif line.startswith("Fix:"):
            if current_error:
                current_error["fix"] = line.replace("Fix:", "").strip()

    if current_error:
        errors.append(current_error)

    return errors


# ============================================================================
# Git Fixtures
# ============================================================================


@pytest.fixture
def git_repo(temp_repo):
    """
    Create a temporary git repository for git-aware tests.

    Returns a Path to the temporary directory with initialized git repo.
    """
    subprocess.run(["git", "init"], cwd=temp_repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=temp_repo, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=temp_repo, capture_output=True)

    # Initial commit
    subprocess.run(["git", "add", "."], cwd=temp_repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=temp_repo, capture_output=True)

    return temp_repo


# ============================================================================
# Skill Fixtures
# ============================================================================


def create_skill_file(repo_path: Path, skill_name: str, valid: bool = True):
    """
    Create a skill file.

    Args:
        repo_path: Path to repository root
        skill_name: Skill name
        valid: If True, creates valid YAML; if False, creates malformed YAML
    """
    skill_dir = repo_path / ".claude" / "skills" / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)

    skill_file = skill_dir / "SKILL.md"

    if valid:
        content = f"""---
name: {skill_name}
description: Test skill {skill_name}
---

This is the {skill_name} skill.
"""
    else:
        content = """---
name: test-skill
description: "Unclosed quote
---

Malformed YAML.
"""

    skill_file.write_text(content)


# ============================================================================
# Flow Fixtures
# ============================================================================


def create_flow_file(repo_path: Path, flow_name: str, agent_references: List[str]):
    """
    Create a flow specification file.

    Args:
        repo_path: Path to repository root
        flow_name: Flow name (e.g., "flow-1")
        agent_references: List of agent names to reference in steps
    """
    flow_path = repo_path / "swarm" / "flows" / f"{flow_name}.md"
    flow_path.parent.mkdir(parents=True, exist_ok=True)

    content = f"# {flow_name}\n\n"
    for i, agent in enumerate(agent_references, start=1):
        content += f"## Step {i}: {agent}\n"
        content += f"Agent: `{agent}`\n\n"
        content += f"Outputs to: RUN_BASE/signal/artifact_{i}.md\n\n"

    flow_path.write_text(content)


# ============================================================================
# Assertion Helpers
# ============================================================================


def assert_validator_passed(result: subprocess.CompletedProcess):
    """Assert that validator passed (exit code 0)."""
    assert result.returncode == 0, f"Validator failed with stderr: {result.stderr}"


def assert_validator_failed(result: subprocess.CompletedProcess):
    """Assert that validator failed (exit code non-zero)."""
    assert result.returncode != 0, f"Validator passed unexpectedly. Stdout: {result.stdout}"


def assert_error_contains(stderr: str, expected_text: str):
    """Assert that stderr contains expected error text."""
    assert expected_text in stderr, f"Expected '{expected_text}' in stderr. Got: {stderr}"


def assert_error_type(stderr: str, error_type: str):
    """Assert that stderr contains error of specific type."""
    assert f"[FAIL] {error_type}:" in stderr, f"Expected error type {error_type} in stderr. Got: {stderr}"


# ============================================================================
# BDD Context Fixture
# ============================================================================


@pytest.fixture
def bdd_context():
    """
    Shared context for BDD steps.
    Stores command results, parsed outputs, and state for assertions.

    Also handles cleanup of temporary files registered in context["cleanup_files"].
    """
    context = {
        "exit_code": None,
        "stdout": "",
        "stderr": "",
        "combined_output": "",
        "json_output": None,
        "parsed_lines": [],
        "cleanup_files": [],
    }
    yield context

    # Cleanup: remove any temporary files registered during the test
    for file_path in context.get("cleanup_files", []):
        try:
            if file_path.exists():
                file_path.unlink()
        except Exception:
            pass  # Best-effort cleanup


# ============================================================================
# Flow Studio Fixtures
# ============================================================================


@pytest.fixture(scope="session")
def flowstudio_client() -> TestClient:
    """
    Provide a session-scoped TestClient for the FastAPI Flow Studio app.

    This fixture creates a single TestClient instance per test session,
    improving test performance by reusing the same client across multiple tests.

    Returns:
        TestClient: FastAPI TestClient connected to the Flow Studio app
    """
    import sys
    from pathlib import Path as PathlibPath

    # Ensure the repo root is in sys.path for imports
    repo_root = PathlibPath(__file__).parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from swarm.tools.flow_studio_fastapi import app
    return TestClient(app)


# ============================================================================
# Pytest Configuration for BDD
# ============================================================================


def pytest_configure(config):
    """Configure pytest, including BDD support."""
    # Suppress gherkin deprecation warnings early (before collection triggers them)
    # This is needed because -W error may process warnings before pyproject.toml filters
    import warnings
    warnings.filterwarnings(
        "ignore",
        message="'maxsplit' is passed as positional argument",
        category=DeprecationWarning,
    )
    warnings.filterwarnings(
        "ignore",
        category=DeprecationWarning,
        module="gherkin.*",
    )
    # Register BDD markers
    config.addinivalue_line(
        "markers",
        "executable: mark test as executable (golden-path BDD scenarios)",
    )
    config.addinivalue_line(
        "markers",
        "bdd: mark test as BDD-driven (runs via pytest-bdd)",
    )
    # Register AC cluster markers (auto-generated by pytest-bdd from feature file tags)
    config.addinivalue_line(
        "markers",
        "AC-SELFTEST-KERNEL-FAST: AC-SELFTEST-KERNEL-FAST cluster",
    )
    config.addinivalue_line(
        "markers",
        "AC-SELFTEST-INTROSPECTABLE: AC-SELFTEST-INTROSPECTABLE cluster",
    )
    config.addinivalue_line(
        "markers",
        "AC-SELFTEST-INDIVIDUAL-STEPS: AC-SELFTEST-INDIVIDUAL-STEPS cluster",
    )
    config.addinivalue_line(
        "markers",
        "AC-SELFTEST-DEGRADED: AC-SELFTEST-DEGRADED cluster",
    )
    config.addinivalue_line(
        "markers",
        "AC-SELFTEST-FAILURE-HINTS: AC-SELFTEST-FAILURE-HINTS cluster",
    )
    config.addinivalue_line(
        "markers",
        "AC-SELFTEST-DEGRADATION-TRACKED: AC-SELFTEST-DEGRADATION-TRACKED cluster",
    )
