# kt-biome

`kt-biome` is the official batteries-included package for [KohakuTerrarium](https://github.com/Kohaku-Lab/KohakuTerrarium).

If KohakuTerrarium is the framework, `kt-biome` is the practical starting point: a package you can install and use immediately for real work, while also treating it as a reference for how creatures, terrariums, plugins, tools, skills, prompts, and I/O modules are meant to be composed.

This package is for people who do not want to begin from a blank `config.yaml`.
It gives you:

- ready-to-run creatures
- reusable terrariums
- a set of production-oriented plugins and tools
- packaged skill bundles
- concrete examples you can inherit from instead of rebuilding from zero

## What `kt-biome` is for

Most users install `kt-biome` for one of three reasons:

1. They want a strong default creature immediately.
2. They want an official base package to inherit from.
3. They want useful packaged modules they can drop into their own configs.

A common workflow looks like this:

- run `@kt-biome/creatures/general` or `@kt-biome/creatures/swe`
- decide what you like
- inherit from that creature in your own package
- add your own prompts, tools, plugins, or terrariums on top

So `kt-biome` is not just a demo repo and not just documentation by example. It is the official out-of-the-box ecosystem for KohakuTerrarium.

## Install

```bash
# install from GitHub
kt install https://github.com/Kohaku-Lab/kt-biome.git

# or install the local checkout in editable mode
kt install ./kt-biome -e
```

After installation, package paths look like:

- `@kt-biome/creatures/general`
- `@kt-biome/creatures/swe`
- `@kt-biome/terrariums/swe_team`
- `@kt-biome/terrariums/ralph_loop`

## Quick start

```bash
# pick and log into a model provider first
kt login codex
kt model default gpt-5.4

# run a general creature
kt run @kt-biome/creatures/general

# run a coding-focused creature
kt run @kt-biome/creatures/swe

# run a research creature
kt run @kt-biome/creatures/researcher

# run a terrarium
kt terrarium run @kt-biome/terrariums/swe_team
```

## Where to start

### Start with `general`

```bash
kt run @kt-biome/creatures/general
```

Use this when you want the default KohakuTerrarium experience with the standard built-in tools and sub-agents, plus packaged skills and low-friction guidance plugins already wired in.

### Start with `swe`

```bash
kt run @kt-biome/creatures/swe
```

Use this when your main work is repository navigation, implementation, debugging, tests, and code review. This is the best default for most software projects.

### Start with `researcher`

```bash
kt run @kt-biome/creatures/researcher
```

Use this when you want a stronger research-and-analysis posture than `general`.

### Use the domain creatures when you already know the task shape

- `music` for LilyPond-first score and composition work
- `video` for HyperFrame / HTML-based video or frame workflows
- `diagrammer` for Mermaid, Graphviz, and D2 work

## Core creatures

### `general`

`general` is the backbone of the package.

It is the creature most other shipped creatures inherit from, and it is meant to feel like the official “default agent” for KohakuTerrarium:

- built-in file and shell tools
- built-in sub-agents
- dynamic skill mode
- wildcard package skill opt-in (`skills: ["*"]`)
- default-on `context_files` and `family_guidance` plugins

If you only try one creature from this package, try this one first.

### `bounded_general`

`bounded_general` is `general` with a shared iteration cap.

It exists mainly as a practical example of the shared iteration-budget feature. Use it when you want the default general creature but want a hard stop on autonomous runs.

### `swe`

`swe` inherits from `general` and adds a stronger software-engineering workflow and system prompt.

It is the best starting point when the job is:

- inspect a repo
- implement a change
- run focused validation
- prepare a clean commit

### `researcher`, `music`, `video`, `diagrammer`

These inherit from the same base philosophy as `general` but narrow the posture toward a task family.

They are useful both as runnable creatures and as inheritance targets for your own package.

## Terrariums

`kt-biome` ships reusable terrariums that demonstrate multi-creature patterns built on top of the framework’s topology, channels, and output wiring.

There is intentionally no single global `root` creature shipped as a reusable package creature. Each terrarium owns its own root prompt and orchestration behavior.

### Included terrariums

- `swe_team` — an implementation/review pipeline using two `swe` instances
- `pair_programming` — a driver/navigator pair using two `swe` instances
- `auto_research` — a multi-step research pipeline over `general` creatures
- `deep_research` — planner/researcher/synthesizer/critic pipeline
- `ralph_loop` — an autonomous initializer/worker loop modeled after the Ralph workflow

### The Ralph loop

`ralph_loop` is the most opinionated terrarium in the package.

It uses two creatures:

- `ralph_initializer` — runs once, scaffolds `AGENTS.md`, `progress.md`, and `NOTES.md`, commits them, then exits
- `ralph_worker` — wakes repeatedly from the `work-log` channel, completes one checkbox item per turn, commits, and posts status back to the same channel

Use it when you want a long-running autonomous implementation loop with durable on-disk task tracking.

Run it with:

```bash
kt terrarium run @kt-biome/terrariums/ralph_loop/
```

Then give the initial goal as your first prompt.

## Plugins

`kt-biome` ships practical plugins that are meant to be reused directly in your own creatures.

Some are convenience upgrades, some are safety layers, and some demonstrate newer framework extension points.

### Low-friction default upgrades

These improve the default coding experience and are enabled by default on `general`:

- `context_files` — walks from the working directory up to the git root, finds files like `AGENTS.md`, `.cursorrules`, and `.hermes.md`, scans them, and injects them into each turn
- `family_guidance` — adds small model-family-specific guidance blocks for OpenAI/Codex and Gemini-style models

### Session control and runtime behavior

- `cost_tracker` — tracks token/cost usage and can now vote to stop the run when budget is exhausted
- `termination_goal` — stops the run when a scratchpad flag becomes truthy
- `seamless_memory` — runs internal reader/writer agents against session memory before and after model calls
- `event_logger` — writes structured JSONL logs of agent activity
- `multimodal_guard` — rewrites multimodal input into text-only placeholders

### Safety and harness plugins

- `checkpoint` — takes a `git stash` checkpoint before destructive tools
- `circuit_breaker` — opens per-tool breakers after repeated failures
- `injection_scanner` — scans tool outputs for prompt-injection patterns and annotates, redacts, or blocks
- `pev_verifier` — independent verifier harness that checks completion and re-injects issues on failure

### Library-only helper

`RAGReader` is no longer a plugin. It lives at `kt_biome.lib.rag_reader` as a reusable library helper for KohakuRAG-style database reads.

Use it from your own plugin or tool when you want:

- structured node reads
- BM25 / vector / hybrid retrieval
- context expansion up the document tree
- tree-based deduplication

## Skills

`kt-biome` also ships reusable skill bundles as `agentskills.io`-style `SKILL.md` directories.

Because `general` declares `skills: ["*"]`, package-provided skills are enabled by default for creatures that inherit from it.

### Included skill bundles

- `git-commit-flow` — safe commit workflow for source-code changes
- `pdf-merge` — merge, split, or reorder PDFs with required page-count verification
- `todo-file` — maintain a user-visible `todo.md` / `plan.md` task list across turns

These can be invoked in three ways:

- automatically, when a matching path pattern activates the skill
- by model invocation with `##skill <name> ...##`
- by user invocation with `/<name> ...`

### Skill creation workflow

`kt-biome` also ships:

- `skill_manage` — a tool for creating or patching reusable `SKILL.md` bundles
- `skill_nudge` — a trigger that periodically reminds the agent to save a repeatable procedure as a skill

This makes the package useful not only for consuming skills, but also for teaching an agent to persist new ones.

## Extra tools, triggers, and I/O modules

Beyond creatures and plugins, `kt-biome` includes reusable packaged modules for more specialized setups.

### Tools

- `bash_docker` — a bash-shaped tool backed by a persistent Docker container
- `bash_ssh` — a bash-shaped tool backed by a pooled SSH session
- `database` — SQLite access tool, marked non-concurrency-safe
- `skill_manage` — reusable skill creation/patch/view tool

### Triggers

- `cron` — full cron-expression trigger with timezone support and backfill behavior
- `skill_nudge` — periodic reminder to save a reusable skill
- `webhook` — HTTP webhook trigger

### I/O modules

- Discord input/output modules
- Telegram input/output modules

The Telegram modules are designed to degrade cleanly when the optional SDK is not installed.

## A good inheritance pattern

A typical downstream package starts from one of these creatures instead of copying configuration by hand.

```yaml
name: my_team_coder
base_config: "@kt-biome/creatures/swe"

controller:
  llm: claude-sonnet-4.6

system_prompt_file: prompts/system.md
```

Then add only what is specific to your package:

- your own system prompt
- your own plugins
- your own custom tools
- your own terrariums

That is the intended use of `kt-biome`: inherit, narrow, and compose.

## Package layout

```text
kt-biome/
  creatures/      reusable creature configs
  terrariums/     reusable terrarium configs
  prompts/        shared prompt fragments
  skills/         packaged SKILL.md bundles
  kt_biome/       Python package for plugins, tools, triggers, I/O, and libs
  kohaku.yaml     package manifest
```

Cross-package references use `@package-name/path` syntax:

```yaml
base_config: "@kt-biome/creatures/swe"
```

## Why this package matters

KohakuTerrarium is flexible enough that a new user can easily end up staring at a blank config and a lot of choices.

`kt-biome` solves that by answering:

- what should a good default creature look like?
- what should a safe coding-oriented creature include?
- what kinds of plugins belong in a real package?
- how should skills, prompts, terrariums, triggers, and I/O modules be organized?

That is why this package exists.

It is the official starting ecosystem, not just a bundle of examples.

## See also

- [Root README](../README.md)
- [Getting Started](../docs/guides/getting-started.md)
- [Creatures Guide](../docs/guides/creatures.md)
- [Plugins Guide](../docs/guides/plugins.md)
- [Examples](../examples/README.md)

## License

KohakuTerrarium License 1.0. See [LICENSE](LICENSE).
