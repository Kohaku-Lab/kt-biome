"""Task-subagent selection in the shipped creature configurations."""

from pathlib import Path

import pytest
import yaml

from kohakuterrarium.bootstrap.subagents import create_subagent_config
from kohakuterrarium.core.config_types import SubAgentConfigItem

ROOT = Path(__file__).resolve().parents[2]


def test_general_exposes_only_bounded_inspection_helpers():
    data = yaml.safe_load(
        (ROOT / "creatures/general/config.yaml").read_text(encoding="utf-8")
    )
    entries = data["subagents"]
    assert entries == [
        {"name": "explore", "type": "builtin"},
        {"name": "critic", "type": "builtin"},
    ]
    for entry in entries:
        config = create_subagent_config(SubAgentConfigItem(**entry), loader=None)
        assert config.max_turns == 14
        assert config.timeout == 600
        assert set(config.tools) == {"read", "glob", "grep", "tree"}
        assert config.default_plugins == []


@pytest.mark.parametrize("name", ["swe", "researcher"])
def test_specialist_creatures_inherit_inspection_helpers(name):
    data = yaml.safe_load(
        (ROOT / f"creatures/{name}/config.yaml").read_text(encoding="utf-8")
    )
    assert data["base_config"] == "@kt-biome/creatures/general"
    assert "subagents" not in data
    assert "subagents" not in data.get("no_inherit", [])
