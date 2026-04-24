"""End-to-end loader test for kt-biome's shipped skill bundles.

Verifies every SKILL.md declared in kt-biome/kohaku.yaml's ``skills:``
block parses cleanly, names match directory names, and frontmatter
exposes a non-empty description.
"""

from pathlib import Path

import pytest
import yaml

from kohakuterrarium.skills import load_skill_from_path

KT_BIOME_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = KT_BIOME_ROOT / "kohaku.yaml"


def _manifest_skill_entries() -> list[dict]:
    if not MANIFEST.exists():
        pytest.skip("kt-biome not checked out alongside this repo")
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    return [e for e in (data.get("skills") or []) if isinstance(e, dict)]


def test_kt_biome_manifest_declares_skills():
    entries = _manifest_skill_entries()
    names = {e.get("name") for e in entries}
    # Must ship at least the three reference bundles.
    assert {"git-commit-flow", "pdf-merge", "todo-file"}.issubset(names)


@pytest.mark.parametrize(
    "entry", _manifest_skill_entries(), ids=lambda e: e.get("name", "?")
)
def test_kt_biome_skill_bundle_loads(entry):
    skill_md = KT_BIOME_ROOT / entry["path"] / "SKILL.md"
    assert skill_md.exists(), f"Missing SKILL.md for {entry['name']}"
    skill = load_skill_from_path(skill_md, origin="package:kt-biome")
    assert skill is not None
    assert skill.name == entry["name"]
    assert skill.description.strip()
    assert skill.body.strip()


def test_pdf_merge_has_paths_glob():
    entries = _manifest_skill_entries()
    pdf = next((e for e in entries if e["name"] == "pdf-merge"), None)
    if pdf is None:
        pytest.skip("pdf-merge bundle not shipped")
    skill_md = KT_BIOME_ROOT / pdf["path"] / "SKILL.md"
    skill = load_skill_from_path(skill_md, origin="package:kt-biome")
    assert skill.paths, "pdf-merge must declare paths for auto-activate"
    assert any("pdf" in p.lower() for p in skill.paths)


def test_todo_file_has_paths_glob():
    entries = _manifest_skill_entries()
    entry = next((e for e in entries if e["name"] == "todo-file"), None)
    if entry is None:
        pytest.skip("todo-file bundle not shipped")
    skill_md = KT_BIOME_ROOT / entry["path"] / "SKILL.md"
    skill = load_skill_from_path(skill_md, origin="package:kt-biome")
    assert skill.paths
    assert any("todo" in p.lower() or "plan" in p.lower() for p in skill.paths)
