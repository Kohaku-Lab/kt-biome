"""Release manifest and distribution version consistency."""

import tomllib
from pathlib import Path

import yaml
from packaging.specifiers import SpecifierSet


ROOT = Path(__file__).resolve().parents[2]


def test_release_metadata_matches_and_requires_inspection_defaults():
    manifest = yaml.safe_load((ROOT / "kohaku.yaml").read_text(encoding="utf-8"))
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert manifest["version"] == project["project"]["version"] == "4.0.0"
    supported = SpecifierSet(manifest["framework"])
    assert "2.1.8" in supported
    assert "2.1.7" not in supported
    assert "3.0.0" not in supported
