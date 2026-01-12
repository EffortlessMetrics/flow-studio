"""Documentation structure and link validation tests.

These tests ensure critical documentation files exist and cross-references are valid.
The operator spine (8 key docs) is enforced to have audience headers.
"""
from pathlib import Path
import re
import pytest

REPO_ROOT = Path(__file__).parent.parent
DOCS_DIR = REPO_ROOT / "docs"

# Operator Spine: The 8 canonical docs every operator should read
# Each tuple is (relative_path_from_repo_root, display_name)
SPINE_DOCS = [
    ("README.md", "README"),
    ("docs/GETTING_STARTED.md", "Getting Started"),
    ("CHEATSHEET.md", "Cheatsheet"),
    ("GLOSSARY.md", "Glossary"),
    ("docs/SELFTEST_SYSTEM.md", "Selftest System"),
    ("docs/FLOW_STUDIO.md", "Flow Studio"),
    ("REPO_MAP.md", "Repo Map"),
    ("docs/VALIDATION_RULES.md", "Validation Rules"),
]


class TestOperatorSpine:
    """Test that operator spine docs exist and have audience headers."""

    @pytest.mark.parametrize("rel_path,name", SPINE_DOCS)
    def test_spine_doc_exists(self, rel_path: str, name: str) -> None:
        """Verify each spine doc exists."""
        path = REPO_ROOT / rel_path
        assert path.exists(), f"Operator spine doc '{name}' not found at {rel_path}"

    @pytest.mark.parametrize("rel_path,name", SPINE_DOCS)
    def test_spine_doc_has_audience_header(self, rel_path: str, name: str) -> None:
        """Verify each spine doc has a 'For:' audience header in first 10 lines."""
        path = REPO_ROOT / rel_path
        if not path.exists():
            pytest.skip(f"File {rel_path} does not exist")

        text = path.read_text(encoding="utf-8")
        head = "\n".join(text.splitlines()[:10])

        # Check for "> For:" pattern (markdown blockquote with audience)
        assert "For:" in head, (
            f"Operator spine doc '{name}' ({rel_path}) should declare an audience header "
            "like '> For: Platform engineers...' in the first 10 lines"
        )

    def test_spine_docs_in_index(self) -> None:
        """Verify all spine docs are referenced in docs/INDEX.md."""
        index_path = DOCS_DIR / "INDEX.md"
        if not index_path.exists():
            pytest.skip("docs/INDEX.md does not exist")

        index_content = index_path.read_text(encoding="utf-8")

        for rel_path, name in SPINE_DOCS:
            # Check that either the relative path or doc name appears in INDEX.md
            assert rel_path in index_content or name in index_content, (
                f"Operator spine doc '{name}' ({rel_path}) should be referenced in docs/INDEX.md"
            )


class TestDocsExistence:
    """Test that critical documentation files exist."""

    REQUIRED_DOCS = [
        "INDEX.md",
        "GOLDEN_RUNS.md",
        "WHY_DEMO_SWARM.md",
        "GETTING_STARTED.md",
        "ADOPTING_SELFTEST_CORE.md",
        "ADOPTING_SWARM_VALIDATION.md",
    ]

    @pytest.mark.parametrize("doc_name", REQUIRED_DOCS)
    def test_required_doc_exists(self, doc_name: str):
        """Verify required documentation files exist."""
        doc_path = DOCS_DIR / doc_name
        assert doc_path.exists(), f"Required doc {doc_name} not found at {doc_path}"


class TestReadmeLinks:
    """Test that README links to key documentation."""

    def test_readme_links_to_index(self):
        """README should link to docs/INDEX.md."""
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        assert "docs/INDEX.md" in readme or "INDEX.md" in readme, \
            "README should link to docs/INDEX.md"

    def test_readme_links_to_golden_runs(self):
        """README should link to GOLDEN_RUNS.md."""
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        assert "GOLDEN_RUNS" in readme, "README should reference GOLDEN_RUNS.md"


class TestCrossReferences:
    """Test documentation cross-references are valid."""

    def test_index_links_valid(self):
        """All relative links in INDEX.md should resolve."""
        index_content = (DOCS_DIR / "INDEX.md").read_text(encoding="utf-8")
        # Find markdown links like [text](path.md) or [text](./path.md)
        link_pattern = r'\[([^\]]+)\]\(([^)]+\.md)\)'
        links = re.findall(link_pattern, index_content)

        for text, path in links:
            if path.startswith("http"):
                continue  # Skip external links
            # Resolve relative to docs dir
            if path.startswith("./"):
                resolved = DOCS_DIR / path[2:]
            elif path.startswith("../"):
                resolved = DOCS_DIR.parent / path[3:]
            else:
                resolved = DOCS_DIR / path

            assert resolved.exists(), f"Broken link in INDEX.md: [{text}]({path}) -> {resolved}"


class TestAdoptionReadiness:
    """Verify adoption readiness documentation."""

    def test_readme_contains_readiness_checklist(self):
        """README.md has adoption readiness checklist section."""
        readme = REPO_ROOT / "README.md"
        content = readme.read_text(encoding="utf-8")

        # Check for the section header
        assert "Are You Ready to Adopt This?" in content or "Ready to Adopt" in content

        # Check for checkbox items
        assert "- [ ]" in content or "- [x]" in content

        # Check for link to adoption playbook
        assert "ADOPTION_PLAYBOOK" in content

    def test_adoption_playbook_has_readiness_checklist(self):
        """ADOPTION_PLAYBOOK.md has readiness checklist."""
        playbook = REPO_ROOT / "docs" / "ADOPTION_PLAYBOOK.md"
        content = playbook.read_text(encoding="utf-8")

        # Check for checkbox prerequisites
        assert "- [ ]" in content or "- [x]" in content
