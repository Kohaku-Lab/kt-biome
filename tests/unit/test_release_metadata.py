"""Release manifest and distribution version consistency."""

import tomllib
from pathlib import Path

import yaml
from packaging.specifiers import SpecifierSet

ROOT = Path(__file__).resolve().parents[2]


def test_release_metadata_matches_and_requires_the_refactored_framework():
    manifest = yaml.safe_load((ROOT / "kohaku.yaml").read_text(encoding="utf-8"))
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert manifest["version"] == project["project"]["version"] == "4.1.0"
    supported = SpecifierSet(manifest["framework"])
    assert manifest["framework"] == ">=2.2.0,<3.0.0"
    assert "2.2.0" in supported
    assert "2.9.0" in supported
    assert "2.1.9" not in supported
    assert "3.0.0" not in supported
