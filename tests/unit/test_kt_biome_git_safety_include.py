"""The ``git-safety`` prompt fragment published by the kt-biome manifest.

A creature that installs kt-biome can ``{% include "git-safety" %}`` the
fragment from its own system prompt; the resolver finds it through the
package's ``prompts:`` slot.
"""

import shutil
from pathlib import Path

import pytest

from kohakuterrarium.packages import install_package, resolve_package_prompt
from kohakuterrarium.prompt import template as tmpl_mod
from kohakuterrarium.prompt.template import render_template_safe

KT_BIOME = Path(__file__).resolve().parents[2]


@pytest.fixture
def kt_biome_installed(tmp_path, monkeypatch):
    """Install the manifest and the fragment into a throwaway packages dir."""
    (tmp_path / "packages").mkdir()
    monkeypatch.setenv("KT_CONFIG_DIR", str(tmp_path))

    fixture = tmp_path / "kt-biome-fixture"
    (fixture / "prompts").mkdir(parents=True)
    shutil.copy(KT_BIOME / "kohaku.yaml", fixture / "kohaku.yaml")
    shutil.copy(
        KT_BIOME / "prompts" / "git-safety.md", fixture / "prompts" / "git-safety.md"
    )
    install_package(str(fixture))

    if tmpl_mod._env.cache is not None:
        tmpl_mod._env.cache.clear()
    yield fixture
    if tmpl_mod._env.cache is not None:
        tmpl_mod._env.cache.clear()


def test_git_safety_fragment_resolves(kt_biome_installed):
    """The manifest declares ``git-safety`` — resolver returns its path."""
    path = resolve_package_prompt("git-safety")
    assert path is not None
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "Never commit" in text
    assert "force push" in text


def test_include_renders_the_fragment(kt_biome_installed):
    """A system prompt including ``git-safety`` renders the fragment's prose."""
    raw = 'You implement code.\n\n{% include "git-safety" %}\n'

    rendered = render_template_safe(raw)

    assert "Never commit, push, or branch unless asked." in rendered
    assert "Never skip hooks" in rendered
    assert "{% include" not in rendered
    assert rendered.startswith("You implement code.")
