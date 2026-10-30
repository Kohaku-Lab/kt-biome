"""Tests for CostTrackerPlugin's budget termination (cluster C.2 consumer).

Exercises the new ``contribute_termination_check`` wiring added in the
1.2 upgrade: when ``budget_usd`` is set and ``stop_at_budget`` is on,
the plugin returns a checker that votes `should_stop=True` once the
running cost meets or exceeds the budget.
"""

from kohakuterrarium.core.termination import TerminationDecision
from kt_biome.plugins.cost_tracker import CostTrackerPlugin


def _drive_cost(plugin: CostTrackerPlugin, amount: float) -> None:
    """Nudge the running total without going through ``post_llm_call``."""
    plugin._total_cost = amount


def test_no_budget_returns_no_checker():
    plugin = CostTrackerPlugin(options={})
    assert plugin.contribute_termination_check() is None


def test_budget_with_stop_disabled_returns_no_checker():
    plugin = CostTrackerPlugin(options={"budget_usd": 5.0, "stop_at_budget": False})
    assert plugin.contribute_termination_check() is None


def test_checker_votes_continue_below_budget():
    plugin = CostTrackerPlugin(options={"budget_usd": 5.0})
    checker = plugin.contribute_termination_check()
    assert checker is not None
    _drive_cost(plugin, 2.5)
    decision = checker(None)
    assert isinstance(decision, TerminationDecision)
    assert decision.should_stop is False


def test_checker_votes_stop_at_budget_boundary():
    plugin = CostTrackerPlugin(options={"budget_usd": 5.0})
    checker = plugin.contribute_termination_check()
    _drive_cost(plugin, 5.0)
    decision = checker(None)
    assert decision.should_stop is True
    assert "budget exhausted" in decision.reason


def test_checker_votes_stop_over_budget():
    plugin = CostTrackerPlugin(options={"budget_usd": 1.0})
    checker = plugin.contribute_termination_check()
    _drive_cost(plugin, 1.23)
    decision = checker(None)
    assert decision.should_stop is True
    assert "$1.23" in decision.reason
