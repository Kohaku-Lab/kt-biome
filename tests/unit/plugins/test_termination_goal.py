"""kt-biome consumer test for pluggable termination (cluster C.2).

Exercises the ``termination_goal`` plugin end-to-end against a real
``TerminationChecker`` with a real ``PluginManager`` — when the
configured scratchpad key becomes truthy, the next termination vote
stops the run with the configured reason.
"""

import pytest

pytest.importorskip("kt_biome")

from kohakuterrarium.core.termination import (
    TerminationChecker,
    TerminationConfig,
)
from kohakuterrarium.modules.plugin.base import PluginContext
from kohakuterrarium.modules.plugin.manager.manager import PluginManager
from kt_biome.plugins.termination_goal import TerminationGoalPlugin


class _DictScratchpad:
    """Minimal ``Scratchpad``-shaped object for the plugin."""

    def __init__(self, data: dict | None = None) -> None:
        self._data = data or {}

    def get(self, key: str):
        return self._data.get(key)

    def set(self, key: str, value) -> None:
        self._data[key] = value

    def to_dict(self) -> dict:
        return dict(self._data)


def _make_checker(scratchpad: _DictScratchpad, plugin: TerminationGoalPlugin):
    checker = TerminationChecker(TerminationConfig())
    manager = PluginManager()
    manager.register(plugin)
    manager._load_context = PluginContext(agent_name="swe", model="m")
    checker.attach_plugins(manager)
    checker.attach_scratchpad(scratchpad)
    checker.start()
    return checker


def test_flag_unset_run_continues():
    pad = _DictScratchpad()
    plugin = TerminationGoalPlugin(
        scratchpad_key="goal_achieved",
        reason="done",
    )
    checker = _make_checker(pad, plugin)
    assert checker.should_terminate() is False


def test_flag_set_true_run_terminates_with_reason():
    pad = _DictScratchpad({"goal_achieved": True})
    plugin = TerminationGoalPlugin(
        scratchpad_key="goal_achieved",
        reason="plan complete",
    )
    checker = _make_checker(pad, plugin)
    assert checker.should_terminate() is True
    assert checker.reason == "plan complete"


def test_flag_set_string_truthy_also_terminates():
    """String encodings of truth are also accepted (cf. docstring)."""
    pad = _DictScratchpad({"goal_achieved": "true"})
    plugin = TerminationGoalPlugin(scratchpad_key="goal_achieved")
    checker = _make_checker(pad, plugin)
    assert checker.should_terminate() is True


def test_custom_key():
    pad = _DictScratchpad({"finish": 1})
    plugin = TerminationGoalPlugin(scratchpad_key="finish", reason="fin")
    checker = _make_checker(pad, plugin)
    assert checker.should_terminate() is True
    assert checker.reason == "fin"


def test_flag_flip_during_run():
    """Plugin must re-read the scratchpad each turn."""
    pad = _DictScratchpad({"goal_achieved": False})
    plugin = TerminationGoalPlugin(scratchpad_key="goal_achieved")
    checker = _make_checker(pad, plugin)
    # First check — flag unset.
    assert checker.should_terminate() is False
    # Flip the flag mid-run.
    pad.set("goal_achieved", True)
    # Next check terminates.
    assert checker.should_terminate() is True
