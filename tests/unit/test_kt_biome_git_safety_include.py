"""kt-biome consumer end-to-end test for Cluster 1 / A.5.

Verifies that the refactor of ``kt-biome/creatures/swe/prompts/system.md``
to use ``{% include "git-safety" %}`` renders correctly, and that the
git-safety prose previously inlined in the creature's system prompt
still appears in the rendered output once the kt-biome package's
``prompts:`` manifest slot is consulted.

This is the "at least one kt-biome consumer end-to-end" bar from
the extension-point decisions §7.3.
"""

import shutil
from pathlib import Path

import pytest

from kohakuterrarium.packages import install_package, resolve_package_prompt
from kohakuterrarium.prompt.template import render_template_safe

KT_BIOME = Path(__file__).resolve().parents[2]


pytestmark = pytest.mark.skipif(
    not KT_BIOME.exists(),
    reason="kt-biome source tree not available",
)


@pytest.fixture
def kt_biome_installed(tmp_path, monkeypatch):
    """Install a copy of the kt-biome source tree into a throwaway
    packages dir so the real user install is untouched.
    """
    import kohakuterrarium.packages as pkg_mod

    packages_root = tmp_path / "packages"
    packages_root.mkdir()
    monkeypatch.setattr(pkg_mod, "PACKAGES_DIR", packages_root)

    # Copy just the manifest + prompts + one creature — keeps the
    # copy small and independent of plugin Python deps that the
    # install-hook would try to resolve.
    fixture = tmp_path / "kt-biome-fixture"
    fixture.mkdir()
    shutil.copy(KT_BIOME / "kohaku.yaml", fixture / "kohaku.yaml")
    (fixture / "prompts").mkdir()
    shutil.copy(
        KT_BIOME / "prompts" / "git-safety.md", fixture / "prompts" / "git-safety.md"
    )
    swe_src = KT_BIOME / "creatures" / "swe"
    swe_dst = fixture / "creatures" / "swe"
    swe_dst.mkdir(parents=True)
    shutil.copy(swe_src / "config.yaml", swe_dst / "config.yaml")
    (swe_dst / "prompts").mkdir()
    shutil.copy(swe_src / "prompts" / "system.md", swe_dst / "prompts" / "system.md")

    install_package(str(fixture))

    # Clear the Jinja template cache so the fresh install is picked up.
    from kohakuterrarium.prompt import template as tmpl_mod

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


def test_swe_system_prompt_renders_fragment(kt_biome_installed):
    """The swe system.md uses ``{% include "git-safety" %}`` — render it."""
    system_md = kt_biome_installed / "creatures" / "swe" / "prompts" / "system.md"
    raw = system_md.read_text(encoding="utf-8")
    # Sanity check: the refactored file uses the include, not inline prose.
    assert '{% include "git-safety" %}' in raw
    # The inline prose must have been removed (no duplication).
    assert "Never commit, push, or branch unless asked." not in raw

    rendered = render_template_safe(raw)
    # After rendering, the include resolves — the prose appears once.
    assert "Never commit, push, or branch unless asked." in rendered
    assert "Never skip hooks" in rendered
    # And the Jinja tag itself is gone.
    assert "{% include" not in rendered
