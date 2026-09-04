---
name: create-agent-connect-graph
description: 'Create a creature folder and wire it into the running graph. Use when asked to add an agent, worker, or specialist to a team.'
license: KohakuTerrarium License 1.0
paths:
  - "creatures/**/config.yaml"
  - "creatures/**/prompts/*.md"
  - "creatures/**/*.py"
  - "terrariums/**/*.yaml"
  - "kohaku.yaml"
---

# create-agent-connect-graph

Use this skill when the user wants a new custom agent (a KohakuTerrarium
**creature**) and wants it connected to the current terrarium graph/team.

A creature is a folder with a config file plus prompt files. A terrarium graph
is changed at runtime only through privileged `group_*` tools. Do not confuse
this with sub-agents: sub-agents are private vertical delegation inside one
creature; spawned creatures are horizontal peers connected by channels/wires.

## 0. Decide the shape

Ask only if the role or connection pattern is genuinely unknown. Otherwise pick
safe defaults:

- base creature: `@kt-biome/creatures/general` for general work,
  `@kt-biome/creatures/swe` for coding work, or another package ref if the
  user names one;
- channel pattern: root/privileged node sends tasks, new worker listens;
  new worker sends results/status, root listens;
- output wire: optional, only for deterministic pipeline hand-off.

Use a normal sub-agent instead of a graph creature when the work is just a
one-shot nested computation that does not need its own tools, model, cwd,
memory, or asynchronous channel loop.

## 1. Create the creature folder

Pick a repository-local folder such as `creatures/<slug>/` or
`.kt/creatures/<slug>/`. Keep the folder self-contained:

```text
creatures/<slug>/
  config.yaml
  prompts/
    system.md
  memory/              # optional
  tools/               # optional custom Python tools
  subagents/           # optional custom sub-agent modules/configs
  plugins/             # optional lifecycle/prompt plugins
  triggers/            # optional custom triggers
  inputs/              # optional custom input modules
  outputs/             # optional custom output modules
```

Minimal inherited creature:

```yaml
# creatures/<slug>/config.yaml
name: <slug>
version: "1.0"
base_config: "@kt-biome/creatures/general"
system_prompt_file: prompts/system.md
```

For a coding specialist, inherit from SWE instead:

```yaml
base_config: "@kt-biome/creatures/swe"
```

Add only fields the new role truly needs. Useful overrides:

```yaml
controller:
  llm: <profile-name>          # optional model override
  reasoning_effort: high       # optional, provider-dependent

# Drop inherited defaults only when the role must be tightly scoped.
# no_inherit: [tools, subagents, plugins]

tools:
  - read
  - grep
  - name: my_tool
    type: custom
    module: ./tools/my_tool.py
    class: MyTool

memory:
  folder: memory/
```

### Custom modules inside the creature folder

A custom agent often needs code, not just a prompt. Put module files under the
creature folder and reference them with `module: ./relative/path.py`. The path
is resolved relative to `creatures/<slug>/`, not the repository root. Use the
YAML key `class` for tools, plugins, inputs, outputs, and triggers; custom
sub-agent config modules use `config: <EXPORTED_CONFIG_NAME>`.

#### Custom tool

Use a tool when the LLM should explicitly call a capability by name.

```python
# creatures/<slug>/tools/project_lookup.py
from kohakuterrarium.modules.tool.base import BaseTool, ToolContext, ToolResult


class ProjectLookupTool(BaseTool):
    needs_context = True

    @property
    def tool_name(self) -> str:
        return "project_lookup"

    @property
    def description(self) -> str:
        return "Look up project-specific facts for this worker."

    async def _execute(
        self,
        args: dict,
        *,
        context: ToolContext | None = None,
    ) -> ToolResult:
        key = args.get("key", "")
        # context.working_dir, context.session, context.environment, etc.
        return ToolResult(output=f"No project fact registered for {key!r}.")
```

```yaml
# creatures/<slug>/config.yaml
tools:
  - name: project_lookup
    type: custom
    module: ./tools/project_lookup.py
    class: ProjectLookupTool
```

#### Custom sub-agent available only inside this creature

Use a sub-agent when the new creature needs private vertical delegation. This
is not a graph peer and does not need `group_*` wiring.

```python
# creatures/<slug>/subagents/domain_review.py
from kohakuterrarium.modules.subagent.config import SubAgentConfig

DOMAIN_REVIEW = SubAgentConfig(
    name="domain_review",
    description="Private domain review helper.",
    system_prompt="Review the input for domain-specific issues. Return bullets.",
    tools=["read", "grep"],
    interactive=False,
    can_modify=False,
)
```

```yaml
subagents:
  - name: domain_review
    type: custom
    module: ./subagents/domain_review.py
    config: DOMAIN_REVIEW
```

#### Custom plugin

Use a plugin when the behavior should run around LLM/tool/sub-agent calls
instead of being invoked as a tool.

```python
# creatures/<slug>/plugins/task_header.py
from kohakuterrarium.modules.plugin.base import BasePlugin


class TaskHeaderPlugin(BasePlugin):
    name = "task_header"

    def __init__(self, header: str = ""):
        super().__init__()
        self.header = header

    def get_content(self, context) -> str | None:
        if not self.header:
            return None
        return f"## Worker routing note\n\n{self.header}"
```

```yaml
plugins:
  - name: task_header
    type: custom
    module: ./plugins/task_header.py
    class: TaskHeaderPlugin
    options:
      header: "Use the review-results channel for final replies."
```

#### Custom trigger/input/output modules

Only add these when the creature has its own event source or output sink. Most
runtime graph workers should communicate through terrarium channels instead.

```yaml
triggers:
  - name: domain_timer
    type: custom
    module: ./triggers/domain_timer.py
    class: DomainTimerTrigger
    options: { interval: 300 }
    prompt: "Check for stale assigned work."

input:
  type: custom
  module: ./inputs/queue_input.py
  class: QueueInput
  options: { path: ./tasks.jsonl }

output:
  type: custom
  module: ./outputs/report_file.py
  class: ReportFileOutput
  options: { path: ./worker-output.md }
```

Custom module checklist:

- import from `kohakuterrarium.modules.*` protocols; do not edit framework
  source;
- keep imports at module top level unless an optional dependency must be lazy;
- pass behavior knobs via `options:` instead of hardcoding secrets;
- if a tool mutates shared state unsafely, set `is_concurrency_safe = False`;
- if custom dependencies are needed, package them in a real package rather than
  relying on ad-hoc `sys.path` hacks.

## 2. Write the system prompt

Put role, responsibilities, routing contract, and safety guidelines in
`prompts/system.md`. Do **not** paste tool lists, tool-call syntax, or full tool
docs there; KohakuTerrarium generates those automatically.

Good prompt skeleton:

```markdown
# <Role name>

You are <role>, a specialist in <domain>.

## Mission
- Do <primary responsibility>.
- Return concise status/results on the configured result channel.
- Ask for clarification only when blocked by missing requirements.

## Collaboration contract
- Treat messages on `<task-channel>` as work requests.
- Send progress or final results to `<result-channel>`.
- Do not assume private sub-agent state is visible to peers; communicate via
  channels when another creature needs to know something.

## Output style
- Prefer short, actionable updates.
- Include file paths, commands, or evidence when relevant.
```

If the new worker should react to specific channels, put that in the prompt;
the actual channel permissions are still configured with `group_channel`.

## 3. Sanity-check the folder

Before spawning, verify the files exist and paths are relative to the creature
folder:

```bash
cat creatures/<slug>/config.yaml
cat creatures/<slug>/prompts/system.md
```

Common mistakes:

- `system_prompt_file` points at `prompts/system.md`, not an absolute path.
- `base_config` uses a package ref like `@kt-biome/creatures/general` or a
  path that exists from the current working directory.
- Custom `module:` paths are relative to the creature folder.

## 4. Snapshot the graph

From a privileged/root creature, inspect the current team first:

```text
group_status(include_spawnable=true, include_history=false)
```

Use the snapshot to avoid duplicate creature names/channels and to confirm the
caller is privileged. If `group_status` is unavailable, you are not in a
privileged graph-editing context; tell the user to run from the root/privileged
node or use `kt terrarium run` / Studio to manage topology.

## 5. Spawn the creature

Create the node with the folder path (or package ref). The new creature is
non-privileged and joins the caller's graph, but it still needs channel/wire
routing before useful work reaches it.

```text
group_add_node(
  config_path="creatures/<slug>",
  name="<display-name>",
  pwd="<working-directory>"        # optional; defaults to caller cwd
)
```

Record the returned `creature_id` or name. Prefer the returned id for later
wiring if names may collide.

## 6. Create channels

Channels are broadcast: every listener receives every message. A creature's own
messages are filtered out, so do not rely on self-loop iteration.

Typical task/result channels:

```text
group_channel(action="create", channel="<slug>-tasks",
              description="Tasks for <display-name>")
group_channel(action="create", channel="<slug>-results",
              description="Results from <display-name>")
```

If the channels already exist, skip creation and only wire missing edges.

## 7. Wire permissions

`group_channel(action="wire", ...)` changes the **target creature's** edge:
`direction="listen"` lets the target receive from the channel;
`direction="send"` lets it publish to the channel.

Typical root-dispatch pattern:

```text
# Worker receives tasks.
group_channel(action="wire", channel="<slug>-tasks",
              creature_id="<worker-id>", direction="listen")

# Worker publishes results.
group_channel(action="wire", channel="<slug>-results",
              creature_id="<worker-id>", direction="send")

# Optional: if the privileged/root caller itself needs explicit edges,
# wire it too (often cross-graph wiring pairs the caller automatically,
# but same-graph updates may need explicit permissions depending on the
# existing topology/prompt contract).
group_channel(action="wire", channel="<slug>-tasks",
              creature_id="<root-id>", direction="send")
group_channel(action="wire", channel="<slug>-results",
              creature_id="<root-id>", direction="listen")
```

For direct one-to-one messages without channels, use `group_send(to, message)`.
For a deterministic pipeline hand-off after each final turn, optionally add an
output wire:

```text
group_wire(action="add", from="<worker-id>", to="<next-id>",
           with_content=true)
```

Use channels for dispatch and conversation; use output wires for pipeline
handoff.

## 8. Verify and dispatch

Run another snapshot:

```text
group_status(include_spawnable=false, include_history=false)
```

Confirm:

- the new creature exists and is `idle` or `not_started`;
- task/result channels exist;
- the worker has `listen` on task and `send` on results;
- the coordinator/root has the opposite permissions when needed.

Then send the first task:

```text
send_channel(channel="<slug>-tasks", message="<clear task payload>")
```

If you need to wake only the new worker and not every listener, use:

```text
group_send(to="<worker-id>", message="<clear task payload>")
```

## 9. Teardown or revise

To pause without deleting session state:

```text
group_stop_node(creature_id="<worker-id>")
group_start_node(creature_id="<worker-id>")
```

To remove cleanly, first delete/unwire edges touching the worker, then remove
it:

```text
group_channel(action="unwire", channel="<slug>-tasks",
              creature_id="<worker-id>", direction="listen")
group_channel(action="unwire", channel="<slug>-results",
              creature_id="<worker-id>", direction="send")
group_remove_node(creature_id="<worker-id>")
```

## Example end-to-end

```text
# Files created:
#   creatures/code-reviewer/config.yaml
#   creatures/code-reviewer/prompts/system.md

group_status(include_spawnable=true)

group_add_node(config_path="creatures/code-reviewer", name="code-reviewer")

group_channel(action="create", channel="review-tasks",
              description="Code review requests")
group_channel(action="create", channel="review-results",
              description="Code review findings")

group_channel(action="wire", channel="review-tasks",
              creature_id="code-reviewer", direction="listen")
group_channel(action="wire", channel="review-results",
              creature_id="code-reviewer", direction="send")

group_status(include_spawnable=false)

send_channel(channel="review-tasks",
             message="Review src/auth.py for correctness and security. Return findings on review-results.")
```
