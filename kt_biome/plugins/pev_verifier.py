"""PEV Verifier Plugin — Plan → Execute → Verify with an independent evaluator.

Implements proposal §4.1 "PEV / Independent verifier" as a kt-biome plugin.
PEV is a convention over existing primitives (subagent + post_llm_call +
inject_event); shipping it here keeps the core framework agnostic to the
fail→inject / fail→halt / fail→replan choice.

Behavior:
  1. On ``post_llm_call``, detect generator completion — no tool calls on
     the last assistant message AND (keyword regex match OR an explicit
     ``done`` tool call this round).
  2. Spawn an internal verifier ``Agent`` programmatically (same pattern as
     ``seamless_memory._create_agent``) with ``read`` / ``grep`` / optional
     ``bash`` (opt-in) tools plus a required ``verdict`` tool.
  3. Feed the verifier the sprint contract, the host's final message, and
     a scratchpad digest.
  4. On fail, inject a fresh ``TriggerEvent`` back into the host queue
     framed as corrective feedback; ``max_rounds`` caps the loop.
  5. On pass, stamp ``pev:passed=true`` on the scratchpad and let the host
     terminate naturally.

Usage (YAML options):

    options:
      model: codex/gpt-5.4              # verifier model (distinct)
      acceptance_criteria:              # required
        - "All files the assistant said it edited exist."
        - "No TODO/FIXME markers were introduced."
      trigger_on_keyword: "all done"    # optional regex
      trigger_on_tool: "done"           # optional generator-done tool
      max_rounds: 3
      agent_names: []                   # empty = all agents
      verifier_tools: ["read", "grep"]  # bash must be opt-in
"""

import json
import re
from typing import Any

from kohakuterrarium.builtins.tool_catalog import get_builtin_tool
from kohakuterrarium.core.events import EventType, TriggerEvent
from kohakuterrarium.modules.plugin.base import BasePlugin, PluginContext
from kohakuterrarium.modules.subagent.base import SubAgent
from kohakuterrarium.modules.subagent.config import SubAgentConfig
from kohakuterrarium.modules.tool.base import BaseTool, ExecutionMode, ToolResult
from kohakuterrarium.utils.logging import get_logger

logger = get_logger(__name__)


# =====================================================================
# Verifier system prompt template
# =====================================================================

_VERIFIER_PROMPT = """\
You are an INDEPENDENT verifier agent. Check whether another agent's \
work satisfies a pre-negotiated sprint contract. You share NO context \
with the generator; treat the handoff below as ground truth.

# Sprint contract — acceptance criteria
{criteria}

# Generator's final message
{final_message}

# Generator's scratchpad (working memory digest)
{scratchpad}

# How to verify
Use `read` and `grep` (and `bash`, if available) to inspect the \
workspace. Be targeted — short evidence-based answers beat long \
speculative ones. Decide pass/fail per criterion based on evidence, \
not the generator's prose.

# How to return
You MUST finish by calling the `verdict` tool exactly once:
- `passed`: true ONLY if every criterion is met.
- `issues`: concrete, actionable problems. Empty when passed=true.
Call `verdict` once. Do not call it twice. After `verdict`, stop."""


# =====================================================================
# Tools
# =====================================================================


class VerdictTool(BaseTool):
    """Final verdict tool the verifier MUST call exactly once."""

    def __init__(self, submit_fn: Any) -> None:
        super().__init__()
        self._submit = submit_fn

    @property
    def tool_name(self) -> str:
        return "verdict"

    @property
    def description(self) -> str:
        return (
            "Submit the final verdict: {passed: bool, issues: list[str]}. "
            "Call exactly once at the end."
        )

    @property
    def execution_mode(self) -> ExecutionMode:
        return ExecutionMode.DIRECT

    def get_parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "passed": {
                    "type": "boolean",
                    "description": "True iff every acceptance criterion is met.",
                },
                "issues": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Concrete, actionable issues. Empty when passed=true.",
                },
            },
            "required": ["passed"],
        }

    async def _execute(self, args: dict[str, Any], **kwargs: Any) -> ToolResult:
        passed = bool(args.get("passed", False))
        raw = args.get("issues") or []
        if not isinstance(raw, list):
            raw = [str(raw)]
        issues = [str(i) for i in raw if str(i).strip()]
        self._submit(passed, issues)
        return ToolResult(
            output="PASS" if passed else f"FAIL ({len(issues)} issue(s))", exit_code=0
        )


# =====================================================================
# Plugin
# =====================================================================


class PEVVerifierPlugin(BasePlugin):
    """Plan → Execute → Verify harness with an independent verifier agent."""

    name = "pev_verifier"
    priority = 60
    description = (
        "Independent-verifier PEV harness: spawns an evaluator agent on "
        "generator completion; re-injects issues on fail."
    )

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        opts = options or {}

        self._criteria: list[str] = _coerce_str_list(opts.get("acceptance_criteria"))
        self._model: str = str(opts.get("model", "")) or "codex/gpt-5.4"
        self._trigger_keyword: str = str(opts.get("trigger_on_keyword", "") or "")
        self._trigger_tool: str = str(opts.get("trigger_on_tool", "") or "")
        self._max_rounds: int = int(opts.get("max_rounds", 3) or 3)
        self._agent_names: set[str] = set(_coerce_str_list(opts.get("agent_names")))
        self._verifier_tool_names: list[str] = _coerce_str_list(
            opts.get("verifier_tools"), default=["read", "grep"]
        )

        self._keyword_re: re.Pattern[str] | None = None
        if self._trigger_keyword:
            try:
                self._keyword_re = re.compile(self._trigger_keyword, re.IGNORECASE)
            except re.error as exc:
                logger.warning(
                    "PEV trigger_on_keyword is not a valid regex; disabling",
                    pattern=self._trigger_keyword,
                    error=str(exc),
                )

        self._disabled: bool = not self._criteria
        if self._disabled:
            logger.warning("PEV verifier has no acceptance_criteria; plugin disabled")

        self._ctx: PluginContext | None = None
        self._verifier: SubAgent | None = None
        self._round_count: int = 0
        self._in_flight: bool = False
        # Verdict capture slot — overwritten on each verifier run.
        self._last_verdict: tuple[bool, list[str]] | None = None

    # ── Lifecycle ────────────────────────────────────────────────────

    async def on_load(self, context: PluginContext) -> None:
        self._ctx = context
        if self._disabled:
            return
        logger.info(
            "PEV verifier loaded",
            verifier_model=self._model,
            criteria_count=len(self._criteria),
            max_rounds=self._max_rounds,
        )

    async def on_unload(self) -> None:
        self._verifier = None

    # ── should_apply ─────────────────────────────────────────────────

    def should_apply(self, context: PluginContext) -> bool:
        """Respect opt-in agent filter. Keep behavior simple and explicit."""
        if self._disabled:
            return False
        if not self._agent_names:
            return True
        return context.agent_name in self._agent_names

    # ── Hooks ────────────────────────────────────────────────────────

    async def post_llm_call(
        self,
        messages: list[dict],
        response: str,
        usage: dict,
        **kwargs: Any,
    ) -> None:
        """Detect generator completion and spawn the verifier when it triggers."""
        if self._disabled or self._ctx is None or self._in_flight:
            return
        if not self.should_apply(self._ctx):
            return
        if self._round_count >= self._max_rounds:
            logger.info("PEV max_rounds reached", max_rounds=self._max_rounds)
            return
        if not self._is_generator_done(messages, response):
            return

        self._in_flight = True
        try:
            await self._run_verification(messages, response)
        except Exception as exc:
            logger.warning(
                "PEV verification failed; host continues unaffected",
                error=str(exc),
                exc_info=True,
            )
        finally:
            self._in_flight = False

    # ── Trigger detection ────────────────────────────────────────────

    def _is_generator_done(self, messages: list[dict], response: str) -> bool:
        """Return True when the assistant message looks like a completion.

        Signal:
        - No tool calls on the LAST assistant message.
        - AND (keyword regex matches OR explicit done-tool was called).
        """
        last_assistant = _last_assistant_message(messages)
        if last_assistant is None:
            return False
        tool_calls = last_assistant.get("tool_calls") or []
        if tool_calls:
            return False

        if self._keyword_re is not None and self._keyword_re.search(response or ""):
            return True
        if self._trigger_tool and _recent_tool_call_present(
            messages, self._trigger_tool
        ):
            return True
        return False

    # ── Verifier orchestration ───────────────────────────────────────

    async def _run_verification(self, messages: list[dict], response: str) -> None:
        verifier = await self._ensure_verifier()
        if verifier is None:
            return

        self._round_count += 1
        self._last_verdict = None

        prompt = _VERIFIER_PROMPT.format(
            criteria=_format_bullets(self._criteria),
            final_message=(response or "(empty)").strip(),
            scratchpad=self._scratchpad_digest() or "(empty)",
        )

        try:
            self._prepare_verifier_run(verifier)
            await verifier.run(prompt)  # Verdict captured via tool callback.
        except Exception as exc:
            logger.warning("PEV verifier run errored", error=str(exc))
            return

        verdict = self._last_verdict
        if verdict is None:
            logger.warning(
                "PEV verifier returned without calling verdict tool; "
                "treating as pass to avoid an infinite loop",
                round=self._round_count,
            )
            self._mark_passed()
            return

        passed, issues = verdict
        if passed:
            logger.info("PEV verdict: PASS", round=self._round_count)
            self._mark_passed()
        else:
            logger.info(
                "PEV verdict: FAIL",
                round=self._round_count,
                issue_count=len(issues),
            )
            self._inject_feedback(issues)

    async def _ensure_verifier(self) -> SubAgent | None:
        if self._verifier is not None:
            return self._verifier
        try:
            self._verifier = await self._create_verifier()
            return self._verifier
        except Exception as exc:
            logger.warning(
                "PEV verifier construction failed; skipping",
                error=str(exc),
                exc_info=True,
            )
            return None

    async def _create_verifier(self) -> SubAgent:
        """Build the verifier through sub-agent-style child plumbing.

        Modules do not create sessions.  The host injects session access;
        when a SessionStore exists, verifier runs are saved via the same
        ``save_subagent`` path used by configured sub-agents.
        """
        if self._ctx is None or self._ctx.host_agent is None:
            raise RuntimeError("PEV verifier requires PluginContext")

        host = self._ctx.host_agent
        parent_llm = getattr(host, "llm", None)
        if parent_llm is None:
            raise RuntimeError("PEV verifier requires host LLM")

        name = f"pev-verifier-{self._ctx.agent_name if self._ctx else 'anon'}"
        tools = self._build_verifier_tools()
        config = SubAgentConfig(
            name=name,
            description="Plugin-private independent verifier",
            tools=[tool.tool_name for tool in tools],
            system_prompt="You are a verifier. Follow the user task exactly.",
            max_turns=5,
            model=self._model,
            tool_format="native",
            budget_inherit=False,
        )
        verifier = SubAgent(
            config=config,
            parent_registry=_PluginChildRegistry(tools),
            llm=_child_llm(parent_llm, self._model, name),
            agent_path=self._ctx.working_dir,
            tool_format="native",
        )
        parent_executor = getattr(host, "executor", None)
        if parent_executor is not None:
            verifier._build_tool_context = parent_executor._build_tool_context

        store = self._ctx.session_store
        if store is not None:
            verifier._session_store = store
            verifier._parent_name = self._ctx.agent_name
        return verifier

    def _prepare_verifier_run(self, verifier: SubAgent) -> None:
        if self._ctx is None:
            return
        store = self._ctx.session_store
        if store is None:
            return
        verifier._session_store = store
        verifier._parent_name = self._ctx.agent_name
        verifier._run_index = store.next_subagent_run(
            self._ctx.agent_name, verifier.config.name
        )

    _VERIFIER_TOOL_NAMES = frozenset({"read", "grep", "bash"})

    def _build_verifier_tools(self) -> list[BaseTool]:
        """Assemble the verifier's tool set from the configured names."""
        tools: list[BaseTool] = []
        for name in self._verifier_tool_names:
            if name.lower() not in self._VERIFIER_TOOL_NAMES:
                logger.warning(
                    "PEV verifier_tools: unknown tool ignored", tool_name=name
                )
                continue
            tools.append(get_builtin_tool(name.lower()))
        tools.append(VerdictTool(self._capture_verdict))
        return tools

    # ── Callbacks from verifier tools ────────────────────────────────

    def _capture_verdict(self, passed: bool, issues: list[str]) -> None:
        self._last_verdict = (passed, list(issues))

    # ── Result handling ──────────────────────────────────────────────

    def _mark_passed(self) -> None:
        if self._ctx is None:
            return
        try:
            self._ctx.set_state("passed", True)
        except Exception as exc:
            logger.debug("PEV set_state failed", error=str(exc))
        scratchpad = self._ctx.scratchpad
        if scratchpad is not None and hasattr(scratchpad, "set"):
            try:
                scratchpad.set("pev:passed", "true")
            except Exception as exc:
                logger.debug("PEV scratchpad set failed", error=str(exc))

    def _inject_feedback(self, issues: list[str]) -> None:
        if self._ctx is None:
            return
        lines = ["The evaluator found these problems, please address them:"]
        if issues:
            lines.extend(f"- {issue}" for issue in issues)
        else:
            lines.append("- (no specific issues — verifier said fail but listed none)")
        event = TriggerEvent(
            type=EventType.USER_INPUT,
            content="\n".join(lines),
            context={"source": "pev_verifier", "round": self._round_count},
            stackable=False,
        )
        try:
            self._ctx.inject_event(event)
        except Exception as exc:
            logger.warning("PEV inject_event failed", error=str(exc))

    # ── Scratchpad digest ────────────────────────────────────────────

    def _scratchpad_digest(self, max_chars: int = 2000) -> str:
        if self._ctx is None:
            return ""
        scratchpad = self._ctx.scratchpad
        if scratchpad is None or not hasattr(scratchpad, "to_dict"):
            return ""
        try:
            data = scratchpad.to_dict()
        except Exception:
            return ""
        if not data:
            return ""
        try:
            serialized = json.dumps(data, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            serialized = "\n".join(f"{k}: {v}" for k, v in data.items())
        if len(serialized) > max_chars:
            serialized = serialized[:max_chars] + "\n... (truncated)"
        return serialized


class _PluginChildRegistry:
    """Minimal parent-registry surface consumed by SubAgent."""

    def __init__(self, tools: list[BaseTool]) -> None:
        self._tools = {tool.tool_name: tool for tool in tools}

    def get_tool(self, tool_name: str) -> BaseTool | None:
        return self._tools.get(tool_name)


def _child_llm(parent_llm: Any, model: str, name: str) -> Any:
    if not model:
        return parent_llm
    try:
        return parent_llm.with_model(model)
    except Exception as exc:
        logger.warning(
            "PEV verifier model override failed; inheriting host LLM",
            child=name,
            model=model,
            error=str(exc),
        )
        return parent_llm


# =====================================================================
# Helpers
# =====================================================================


def _last_assistant_message(messages: list[dict]) -> dict | None:
    """Return the final assistant message in ``messages`` or None."""
    for msg in reversed(messages or []):
        if msg.get("role") == "assistant":
            return msg
    return None


def _recent_tool_call_present(messages: list[dict], tool_name: str) -> bool:
    """Return True iff the most recent assistant turn called ``tool_name``.

    We look back through assistant messages until the previous user turn;
    that bounds the window to "this generator round".
    """
    for msg in reversed(messages or []):
        role = msg.get("role")
        if role == "user":
            return False
        if role != "assistant":
            continue
        for call in msg.get("tool_calls") or []:
            fn = call.get("function") if isinstance(call, dict) else None
            if isinstance(fn, dict) and fn.get("name") == tool_name:
                return True
            if isinstance(call, dict) and call.get("name") == tool_name:
                return True
    return False


def _format_bullets(items: list[str]) -> str:
    if not items:
        return "(none provided)"
    return "\n".join(f"- {item}" for item in items)


def _coerce_str_list(value: Any, default: list[str] | None = None) -> list[str]:
    """Normalise YAML-loaded option to ``list[str]``.

    - ``None`` / missing → ``default or []``.
    - A bare string is wrapped.
    - All entries are stringified and stripped; empties are dropped.
    - An explicit empty list is preserved (no silent fallback).
    """
    if value is None:
        return list(default) if default else []
    if isinstance(value, str):
        value = [value]
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
    return out
