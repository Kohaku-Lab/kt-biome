"""Model-family-gated guidance plugin.

Injects a small system-level guidance block into the message list at
``pre_llm_call`` time, gated on the active LLM model id matching one of a
configured set of regex patterns.

Reference: proposal §4.5 and Hermes-agent's per-family prompt guidance
(``OPENAI_MODEL_EXECUTION_GUIDANCE`` / ``GOOGLE_MODEL_OPERATIONAL_GUIDANCE``).
Guidance text below is an original paraphrase — short, plain prose, no
vendor-licensed text.

Usage::

    plugins:
      - name: family_guidance
        type: package
        module: kt_biome.plugins.family_guidance
        class: FamilyGuidancePlugin
        options:
          enabled: true
          include_defaults: true
          position: after_system        # after_system | prepend_first
          dedup: true
          agent_names: []               # [] = apply to every agent
          profiles:                     # extra user profiles, merged in
            - name: custom-1
              patterns:
                - "^my-provider/.*"
              guidance: |
                Prefer the tools installed on this runner.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from kohakuterrarium.modules.plugin.base import BasePlugin, PluginContext
from kohakuterrarium.utils.logging import get_logger

logger = get_logger(__name__)


# =====================================================================
# Default guidance blocks
# =====================================================================
#
# Both blocks are original paraphrases. They are short, model-generic,
# and safe to append verbatim to a system conversation. Edit with care:
# the dedup sentinel in _sentinel() is built from the profile name, so
# changing these strings does not break dedup, but does affect prompt
# tokens for every agent using the defaults.

OPENAI_FAMILY_GUIDANCE: str = (
    "# Execution discipline\n"
    "- Use tools whenever they would make the answer more correct, more "
    "complete, or better grounded. Do not stop early if another tool call "
    "would materially improve the result.\n"
    "- Never answer from memory for things tools can check: arithmetic, "
    "timestamps, file contents, system state, git history, current facts. "
    "Call the appropriate tool instead.\n"
    "- Act on the obvious default interpretation of a request rather than "
    "asking for clarification. Only ask when the ambiguity genuinely "
    "changes what you would do.\n"
    "- Check prerequisites before acting. If a step depends on prior "
    "output, resolve that dependency first.\n"
    "- Before declaring a task done, verify: does the output satisfy every "
    "stated requirement, are factual claims backed by tool output, does "
    "the format match what was asked?\n"
    "- If required context is missing, retrieve it with the right tool "
    "rather than guessing. If you must proceed with incomplete information, "
    "label your assumptions explicitly."
)

GEMINI_FAMILY_GUIDANCE: str = (
    "# Operational directives\n"
    "- Use absolute file paths for every file operation. Combine the "
    "project root with any relative path before calling a tool.\n"
    "- Verify before you edit: read the file or search the project to "
    "confirm structure and contents rather than guessing.\n"
    "- Do not assume a dependency is available. Check the project's "
    "manifest (pyproject.toml, package.json, requirements.txt, Cargo.toml, "
    "etc.) before importing or invoking it.\n"
    "- Prefer non-interactive flags (``-y``, ``--yes``, ``--non-interactive``) "
    "so CLI tools never block waiting on a prompt.\n"
    "- When you need several independent reads or lookups, issue the tool "
    "calls in parallel in a single turn rather than one-by-one.\n"
    "- Keep narration short — a couple of sentences, not paragraphs. "
    "Prefer showing the action and the result.\n"
    "- Work the task to completion autonomously; do not stop at a plan."
)

# Patterns follow the proposal spec.  ``^`` + optional provider prefix +
# family token + ``-`` or ``.`` separator so we match ``gpt-5.4`` /
# ``codex/gpt-5.4`` / ``openai/o3-mini`` etc., but not ``gptfoo``.
_DEFAULT_OPENAI_PATTERNS: tuple[str, ...] = (
    r"^(openai/|codex/)?(gpt|codex|o[134])[-.]",
)
_DEFAULT_GEMINI_PATTERNS: tuple[str, ...] = (r"^(gemini/|google/)?(gemini|gemma)[-.]",)


# =====================================================================
# Profile model
# =====================================================================


@dataclass
class _Profile:
    """Compiled guidance profile."""

    name: str
    patterns: list[re.Pattern[str]]
    guidance: str

    def matches(self, model: str) -> bool:
        return any(p.search(model) for p in self.patterns)


def _compile_patterns(raw: list[str] | tuple[str, ...]) -> list[re.Pattern[str]]:
    compiled: list[re.Pattern[str]] = []
    for pat in raw:
        try:
            compiled.append(re.compile(pat, re.IGNORECASE))
        except re.error as exc:
            logger.warning("family_guidance: bad pattern %r (%s)", pat, exc)
    return compiled


def _default_profiles() -> list[_Profile]:
    return [
        _Profile(
            name="openai-family",
            patterns=_compile_patterns(_DEFAULT_OPENAI_PATTERNS),
            guidance=OPENAI_FAMILY_GUIDANCE,
        ),
        _Profile(
            name="gemini-family",
            patterns=_compile_patterns(_DEFAULT_GEMINI_PATTERNS),
            guidance=GEMINI_FAMILY_GUIDANCE,
        ),
    ]


def _parse_user_profiles(raw: list[dict[str, Any]] | None) -> list[_Profile]:
    out: list[_Profile] = []
    if not raw:
        return out
    for entry in raw:
        if not isinstance(entry, dict):
            logger.warning("family_guidance: profile entry not a dict, skipped")
            continue
        name = str(entry.get("name", "")).strip()
        patterns = entry.get("patterns") or []
        guidance = entry.get("guidance", "")
        if not name or not patterns or not guidance:
            logger.warning(
                "family_guidance: profile skipped (missing name/patterns/guidance): %r",
                entry,
            )
            continue
        if not isinstance(patterns, (list, tuple)):
            patterns = [patterns]
        out.append(
            _Profile(
                name=name,
                patterns=_compile_patterns([str(p) for p in patterns]),
                guidance=str(guidance).rstrip() + "\n",
            )
        )
    return out


# =====================================================================
# Sentinel (dedup marker)
# =====================================================================


def _sentinel(profile_name: str) -> str:
    """Inline marker used to detect already-injected guidance."""
    return f"<!--kt:family-guidance:{profile_name}-->"


def _contains_sentinel(messages: list[dict], marker: str) -> bool:
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str) and marker in content:
            return True
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text") or part.get("content") or ""
                    if isinstance(text, str) and marker in text:
                        return True
    return False


# =====================================================================
# Plugin
# =====================================================================


@dataclass
class _Settings:
    enabled: bool = True
    include_defaults: bool = True
    position: str = "after_system"  # after_system | prepend_first
    dedup: bool = True
    agent_names: list[str] = field(default_factory=list)


class FamilyGuidancePlugin(BasePlugin):
    """Inject per-model-family system guidance on ``pre_llm_call``."""

    name = "family_guidance"
    priority = 30  # Runs before most transformers so later plugins see guidance.

    def __init__(self, options: dict[str, Any] | None = None):
        opts = options or {}
        self._settings = _Settings(
            enabled=bool(opts.get("enabled", True)),
            include_defaults=bool(opts.get("include_defaults", True)),
            position=str(opts.get("position", "after_system")),
            dedup=bool(opts.get("dedup", True)),
            agent_names=list(opts.get("agent_names") or []),
        )
        if self._settings.position not in ("after_system", "prepend_first"):
            logger.warning(
                "family_guidance: unknown position %r, falling back to after_system",
                self._settings.position,
            )
            self._settings.position = "after_system"

        profiles: list[_Profile] = []
        if self._settings.include_defaults:
            profiles.extend(_default_profiles())
        profiles.extend(_parse_user_profiles(opts.get("profiles")))
        self._profiles = profiles

        self._ctx: PluginContext | None = None

    # ── Lifecycle ────────────────────────────────────────────────────

    async def on_load(self, context: PluginContext) -> None:
        self._ctx = context
        logger.info(
            "family_guidance loaded (profiles=%d, enabled=%s)",
            len(self._profiles),
            self._settings.enabled,
        )

    # ── Gating ───────────────────────────────────────────────────────

    def should_apply(self, context: PluginContext) -> bool:
        """Optional agent-name restriction; callable from manager or internal."""
        if not self._settings.enabled:
            return False
        allowed = self._settings.agent_names
        if not allowed:
            return True
        return context.agent_name in allowed

    # ── Hooks ────────────────────────────────────────────────────────

    async def pre_llm_call(self, messages: list[dict], **kwargs) -> list[dict] | None:
        if not self._settings.enabled:
            return None
        if not self._profiles:
            return None
        if not isinstance(messages, list):
            return None
        if not messages:
            return None

        # Respect agent_names gating even without the manager calling should_apply.
        if self._ctx and not self.should_apply(self._ctx):
            return None

        model = str(kwargs.get("model") or (self._ctx.model if self._ctx else "") or "")
        if not model:
            return None

        matched: list[_Profile] = []
        for prof in self._profiles:
            if not prof.matches(model):
                continue
            if self._settings.dedup and _contains_sentinel(
                messages, _sentinel(prof.name)
            ):
                continue
            matched.append(prof)

        if not matched:
            return None

        body_parts: list[str] = []
        for prof in matched:
            body_parts.append(f"{_sentinel(prof.name)}\n{prof.guidance.rstrip()}")
        body = "\n\n".join(body_parts)

        new_messages = list(messages)
        injection = {"role": "system", "content": body}

        if self._settings.position == "prepend_first" or not new_messages:
            insert_idx = 0
        else:
            insert_idx = 0
            for i, msg in enumerate(new_messages):
                if isinstance(msg, dict) and msg.get("role") == "system":
                    insert_idx = i + 1
                    break
        new_messages.insert(insert_idx, injection)

        logger.debug(
            "family_guidance: injected %d profile(s) for model=%s",
            len(matched),
            model,
        )
        return new_messages
