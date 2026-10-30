"""Seamless Memory Plugin — fully adaptive memory read/write.

Self-contained: agent configs, prompts, and tools are all built
programmatically. No external creature configs or files needed.

Two internal agents with real tools (native function calling):
  **Reader**: memory_search → inject_to_context → done
  **Writer**: write_to_memory → done

Both run at pre_llm_call and post_llm_call in parallel.
All storage uses the host agent's SessionMemory (same FTS + vector).

Usage in config.yaml:

    plugins:
      - name: seamless_memory
        type: package
        module: kt_biome.plugins.seamless_memory
        class: SeamlessMemoryPlugin
        options:
          model: openrouter/xiaomi/mimo-v2-flash
          min_turns_before_active: 2
"""

import asyncio
import time
from typing import Any

from kohakuterrarium.core.events import EventType, TriggerEvent
from kohakuterrarium.modules.plugin.base import BasePlugin, PluginContext
from kohakuterrarium.modules.subagent.base import SubAgent
from kohakuterrarium.modules.subagent.config import SubAgentConfig
from kohakuterrarium.modules.tool.base import BaseTool, ExecutionMode, ToolResult
from kohakuterrarium.session.memory.embedding import create_embedder
from kohakuterrarium.session.memory.index import SessionMemory
from kohakuterrarium.utils.logging import get_logger

logger = get_logger(__name__)


# =====================================================================
# Tools
# =====================================================================


class MemorySearchTool(BaseTool):
    """Search the host agent's session memory."""

    def __init__(self, search_fn):
        super().__init__()
        self._search = search_fn

    @property
    def tool_name(self) -> str:
        return "memory_search"

    @property
    def description(self) -> str:
        return (
            "Search past session memory. Use creative queries — "
            "think about related concepts, not just the user's exact words. "
            "You can call this multiple times with different queries."
        )

    @property
    def execution_mode(self) -> ExecutionMode:
        return ExecutionMode.DIRECT

    def prompt_contribution(self) -> str | None:
        # Cluster 5 / E.1 self-described guidance. Kept short — long
        # docs stay behind ##info memory_search##.
        return (
            "When recalling prior work with `memory_search`, query with "
            "related concepts — not just the user's verbatim keywords. "
            "Call it multiple times with different angles."
        )

    def get_parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        }

    async def _execute(self, args: dict[str, Any], **kwargs: Any) -> ToolResult:
        query = args.get("query", "")
        if not query:
            return ToolResult(error="No query provided")
        results = self._search(query)
        if not results:
            return ToolResult(output="(no results)", exit_code=0)
        lines = []
        for r in results:
            age = f" ({r['age']})" if r.get("age") else ""
            lines.append(f"[{r.get('type', '?')}]{age} {r['content']}")
        return ToolResult(output="\n".join(lines), exit_code=0)


class InjectToContextTool(BaseTool):
    """Inject a memory into the host agent's context."""

    def __init__(self, inject_fn):
        super().__init__()
        self._inject = inject_fn

    @property
    def tool_name(self) -> str:
        return "inject_to_context"

    @property
    def description(self) -> str:
        return (
            "Inject a memory into the host agent's context. "
            "Only call if it would genuinely change the host's behavior."
        )

    @property
    def execution_mode(self) -> ExecutionMode:
        return ExecutionMode.DIRECT

    def get_parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Memory text to inject"},
                "critical": {
                    "type": "boolean",
                    "description": "True = host is about to make a mistake, fire immediate new round",
                },
            },
            "required": ["content"],
        }

    async def _execute(self, args: dict[str, Any], **kwargs: Any) -> ToolResult:
        content = args.get("content", "")
        critical = args.get("critical", False)
        if not content:
            return ToolResult(error="No content")
        self._inject(content, critical)
        return ToolResult(
            output=f"Injected ({'critical' if critical else 'normal'})", exit_code=0
        )


class WriteToMemoryTool(BaseTool):
    """Write a new entry to the host agent's session memory."""

    def __init__(self, write_fn):
        super().__init__()
        self._write = write_fn

    @property
    def tool_name(self) -> str:
        return "write_to_memory"

    @property
    def description(self) -> str:
        return (
            "Write a memory entry. Rewrite content to be search-friendly: "
            "concise, standalone facts. Don't store raw conversation."
        )

    @property
    def execution_mode(self) -> ExecutionMode:
        return ExecutionMode.DIRECT

    def get_parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Memory content (rewritten for searchability)",
                },
                "category": {
                    "type": "string",
                    "enum": [
                        "fact",
                        "decision",
                        "preference",
                        "lesson",
                        "context",
                        "entity",
                    ],
                    "description": "Category",
                },
            },
            "required": ["content"],
        }

    async def _execute(self, args: dict[str, Any], **kwargs: Any) -> ToolResult:
        content = args.get("content", "")
        category = args.get("category", "fact")
        if not content:
            return ToolResult(error="No content")
        self._write(content, category)
        return ToolResult(output=f"Stored [{category}]", exit_code=0)


class DoneTool(BaseTool):
    """Signal no action needed."""

    @property
    def tool_name(self) -> str:
        return "done"

    @property
    def description(self) -> str:
        return "No memory action needed this turn. Call this to finish."

    @property
    def execution_mode(self) -> ExecutionMode:
        return ExecutionMode.DIRECT

    async def _execute(self, args: dict[str, Any], **kwargs: Any) -> ToolResult:
        return ToolResult(output="ok", exit_code=0)


# =====================================================================
# Plugin
# =====================================================================


class SeamlessMemoryPlugin(BasePlugin):
    name = "seamless_memory"
    priority = 45

    def __init__(self, options: dict[str, Any] | None = None):
        opts = options or {}
        self._model = opts.get("model", "openrouter/xiaomi/mimo-v2-flash")
        self._min_turns = int(opts.get("min_turns_before_active", 2))

        self._ctx: PluginContext | None = None
        self._read_agent: SubAgent | None = None
        self._write_agent: SubAgent | None = None
        self._session_memory: SessionMemory | None = None
        self._turn_count = 0

        self._pending_injections: list[str] = []
        self._pending_critical: list[str] = []

    # ── Lifecycle ────────────────────────────────────────────────────

    async def on_load(self, context: PluginContext) -> None:
        self._ctx = context
        self._init_session_memory()
        logger.info("Seamless memory loaded", model=self._model)

    async def on_unload(self) -> None:
        self._read_agent = None
        self._write_agent = None

    def _init_session_memory(self) -> None:
        if self._ctx is None:
            return
        store = self._ctx.session_store
        if store is None:
            return
        try:
            embedder = None
            embed_config = store.state.get("embedding_config")
            if embed_config:
                embedder = create_embedder(embed_config)
            self._session_memory = SessionMemory(
                str(store.path), embedder=embedder, store=store
            )
        except Exception as e:
            logger.warning("Session memory init failed", error=str(e))

    # ── Programmatic agent creation ──────────────────────────────────

    async def _get_read_agent(self) -> SubAgent:
        if self._read_agent is None:
            self._read_agent = await self._create_agent(
                "seamless-reader",
                _READER_PROMPT,
                [
                    MemorySearchTool(self._do_search),
                    InjectToContextTool(self._do_inject),
                    DoneTool(),
                ],
            )
        return self._read_agent

    async def _get_write_agent(self) -> SubAgent:
        if self._write_agent is None:
            self._write_agent = await self._create_agent(
                "seamless-writer",
                _WRITER_PROMPT,
                [WriteToMemoryTool(self._do_write), DoneTool()],
            )
        return self._write_agent

    async def _create_agent(
        self, name: str, prompt: str, tools: list[BaseTool]
    ) -> SubAgent:
        """Build a plugin-private child runner using sub-agent plumbing.

        Modules do not own sessions.  If the host has a SessionStore, the
        SubAgent records through that store exactly like configured
        sub-agents do: parent injects the store, child saves its run.
        """
        if self._ctx is None or self._ctx.host_agent is None:
            raise RuntimeError("seamless_memory child agent requires PluginContext")

        host = self._ctx.host_agent
        parent_llm = getattr(host, "llm", None)
        if parent_llm is None:
            raise RuntimeError("seamless_memory child agent requires host LLM")

        llm = _child_llm(parent_llm, self._model, name)
        config = SubAgentConfig(
            name=name,
            description="Plugin-private seamless memory helper",
            tools=[tool.tool_name for tool in tools],
            system_prompt=prompt,
            max_turns=3,
            model=self._model,
            tool_format="native",
            budget_inherit=False,
        )
        registry = _PluginChildRegistry(tools)
        agent = SubAgent(
            config=config,
            parent_registry=registry,
            llm=llm,
            agent_path=self._ctx.working_dir,
            tool_format="native",
        )
        parent_executor = getattr(host, "executor", None)
        if parent_executor is not None:
            agent._build_tool_context = parent_executor._build_tool_context

        store = self._ctx.session_store
        if store is not None:
            agent._session_store = store
            agent._parent_name = self._ctx.agent_name
        return agent

    # ── Tool callbacks ───────────────────────────────────────────────

    def _do_search(self, query: str) -> list[dict]:
        if not self._session_memory:
            return []
        try:
            hits = self._session_memory.search(
                query=query,
                mode="hybrid",
                k=8,
                agent=self._ctx.agent_name if self._ctx else None,
            )
            return [
                {
                    "content": h.content,
                    "type": h.block_type,
                    "score": h.score,
                    "age": h.age_str,
                }
                for h in hits
            ]
        except Exception:
            return []

    def _do_inject(self, content: str, critical: bool = False) -> None:
        if critical:
            self._pending_critical.append(content)
        else:
            self._pending_injections.append(content)

    def _do_write(self, content: str, category: str = "fact") -> None:
        if not self._session_memory or not self._ctx:
            return
        agent_name = self._ctx.agent_name
        store = self._ctx.session_store
        if store is not None:
            store.append_event(
                agent_name,
                "memory_note",
                {"content": f"[{category}] {content}", "source": "seamless_memory"},
            )
        try:
            tagged = f"[memory:{category}] {content}"
            meta = {
                "agent": agent_name,
                "type": "memory",
                "ts": time.time(),
                "round": 0,
                "block": 0,
            }
            self._session_memory._fts[tagged] = meta
            if self._session_memory._has_vectors and self._session_memory._vec:
                vec = self._session_memory._embedder.encode_one(tagged)
                self._session_memory._vec.insert(vec, {**meta, "content": tagged})
        except Exception as e:
            logger.debug("Memory index failed", error=str(e))

    # ── Hooks ────────────────────────────────────────────────────────

    async def pre_llm_call(self, messages: list[dict], **kwargs) -> list[dict] | None:
        self._turn_count += 1
        modified = self._flush_injections(messages)

        if self._turn_count < self._min_turns:
            return modified

        context = _extract_recent(messages)
        if not context:
            return modified

        read_agent, write_agent = await asyncio.gather(
            self._get_read_agent(), self._get_write_agent()
        )
        await asyncio.gather(
            self._run_agent(read_agent, context, "pre_llm"),
            self._run_agent(write_agent, context, "pre_llm"),
        )

        if self._pending_injections or self._pending_critical:
            modified = self._flush_injections(modified or messages)

        return modified

    async def post_llm_call(
        self, messages: list[dict], response: str, usage: dict, **kwargs
    ) -> None:
        if self._turn_count < self._min_turns:
            return

        context = _extract_recent(messages)
        if response:
            context += f"\n[assistant] {response}"

        read_agent, write_agent = await asyncio.gather(
            self._get_read_agent(), self._get_write_agent()
        )
        await asyncio.gather(
            self._run_agent(read_agent, context, "post_llm"),
            self._run_agent(write_agent, context, "post_llm"),
        )

        if self._pending_critical and self._ctx:
            text = "\n".join(f"- {c}" for c in self._pending_critical)
            self._pending_critical = []
            self._ctx.inject_event(
                TriggerEvent(
                    type=EventType.CONTEXT_UPDATE,
                    content=f"[Memory recall — important context]\n{text}",
                    source="seamless_memory",
                )
            )
            logger.info("Critical memory — fired new round")

    async def on_compact_end(self, summary: str, messages_removed: int) -> None:
        if not self._session_memory or not self._ctx:
            return
        try:
            store = self._ctx.session_store
            if store is not None:
                events = store.get_events(self._ctx.agent_name)
                self._session_memory.index_events(self._ctx.agent_name, events)
        except Exception as e:
            logger.debug("Re-index failed", error=str(e))

    async def on_agent_stop(self) -> None:
        logger.info("Seamless memory stopping", turns=self._turn_count)

    # ── Internal ─────────────────────────────────────────────────────

    async def _run_agent(self, agent: SubAgent, context: str, phase: str) -> None:
        try:
            self._prepare_child_run(agent)
            prompt = f"[{phase}] Current conversation:" + "\n" + context
            await agent.run(prompt)
        except Exception as e:
            logger.debug("Memory agent error", phase=phase, error=str(e))

    def _prepare_child_run(self, agent: SubAgent) -> None:
        if self._ctx is None:
            return
        store = self._ctx.session_store
        if store is None:
            return
        agent._session_store = store
        agent._parent_name = self._ctx.agent_name
        agent._run_index = store.next_subagent_run(
            self._ctx.agent_name, agent.config.name
        )

    def _flush_injections(self, messages: list[dict]) -> list[dict] | None:
        items = list(self._pending_injections)
        self._pending_injections = []
        if not items:
            return None
        lines = ["[Relevant context from past sessions]"]
        for item in items:
            lines.append(f"- {item}")
        modified = list(messages)
        insert_idx = 1
        for i, msg in enumerate(modified):
            if msg.get("role") == "system":
                insert_idx = i + 1
                break
        modified.insert(insert_idx, {"role": "system", "content": "\n".join(lines)})
        return modified


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
            "Seamless memory child model override failed; inheriting host LLM",
            child=name,
            model=model,
            error=str(exc),
        )
        return parent_llm


# =====================================================================
# Helpers
# =====================================================================


def _extract_recent(messages: list[dict], max_chars: int = 4000) -> str:
    parts: list[str] = []
    total = 0
    for msg in reversed(messages):
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                p.get("text", "") or p.get("content", "")
                for p in content
                if isinstance(p, dict)
            )
        if not content:
            continue
        if total + len(content) > max_chars:
            break
        parts.append(f"[{msg.get('role', '?')}] {content}")
        total += len(content)
    return "\n".join(reversed(parts))


# =====================================================================
# Agent prompts
# =====================================================================

_READER_PROMPT = """\
You are a memory reader agent inside a plugin. You observe conversation \
and decide whether past memories would help the host agent.

Your tools:
- memory_search(query): search past sessions. Be CREATIVE — think about \
related concepts, similar problems, past decisions. Call multiple times \
with different queries if needed.
- inject_to_context(content, critical): inject a memory into the host's \
context. Set critical=true ONLY if the host is about to repeat a known \
mistake or is missing essential context.
- done(): no memory action needed. Call this to finish.

MOST turns need NO lookup. Call done() unless past context would \
genuinely help. Always call done() when finished."""

_WRITER_PROMPT = """\
You are a memory writer agent inside a plugin. You observe conversation \
and decide whether anything is worth remembering for future sessions.

Your tools:
- write_to_memory(content, category): store a memory. Categories: fact, \
decision, preference, lesson, context, entity.
- done(): nothing worth storing. Call this to finish.

REWRITE content for searchability — concise standalone facts:
  BAD: "The user discussed authentication and mentioned they tried JWT"
  GOOD: "User prefers JWT over session cookies for authentication"

User preferences/corrections: ALWAYS store.
Decisions/lessons: ALWAYS store.
Routine tool calls/boilerplate: NEVER store.
MOST turns need NO write. Always call done() when finished."""
