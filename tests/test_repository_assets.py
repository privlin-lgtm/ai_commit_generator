import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def test_ci_has_required_jobs_and_quality_commands() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    jobs = workflow["jobs"]

    assert set(jobs) == {"lint", "test", "build", "security_scan"}
    rendered = json.dumps(jobs)
    for command in (
        "ruff check .",
        "ruff format --check .",
        "mypy src",
        "pytest --cov-fail-under=90",
        "bandit -r src -q",
        "pip-audit",
        "python -m build",
    ):
        assert command in rendered


def test_readme_internal_links_and_svg_are_valid() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    links = re.findall(r"\]\((docs/[^)#]+)\)", readme)

    assert links
    assert all((ROOT / link).is_file() for link in links)
    asset = ROOT / "docs" / "assets" / "commitgen-cli.svg"
    root = ET.parse(asset).getroot()
    assert root.tag.endswith("svg")
    assert root.find("{http://www.w3.org/2000/svg}title") is not None
    assert "<script" not in asset.read_text(encoding="utf-8").casefold()


def test_architecture_mermaid_fences_are_balanced() -> None:
    architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    assert architecture.count("```mermaid") == 8
    assert architecture.count("```") % 2 == 0
