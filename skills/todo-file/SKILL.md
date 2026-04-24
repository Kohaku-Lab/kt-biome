---
name: todo-file
description: Maintain a simple todo.md / plan.md workspace for multi-step tasks. Use when the user says "make a plan", "track this as a task list", or whenever a non-trivial multi-step task would benefit from being checkpointed to disk between agent turns.
license: KohakuTerrarium License 1.0
paths:
  - "todo.md"
  - "plan.md"
  - "TODO.md"
  - "PLAN.md"
---

# todo-file

Use this skill to maintain a checkbox-style task list in a plain
markdown file the user can read and edit alongside the agent.

## When

Start a todo file when:

- The user says "plan this out first", "break it down", or
  "let's track subtasks".
- The task has 3+ independent subtasks.
- The task will likely span multiple agent turns.

Skip the file when the whole task fits in one or two tool calls.

## Shape

Write the file at `<cwd>/todo.md` (or `plan.md` if the user already
uses that name). Structure:

```markdown
# Task: <short title>

Goal: <one-paragraph description of what "done" looks like.>

## Open
- [ ] subtask one
- [ ] subtask two

## Done
- [x] first preflight step
```

One line per subtask. Tick with `[x]` when finished — keep done items
in the Done section so the open list stays short.

## Discipline

- **Before starting work**: append the task list to the file and show
  the user before acting on it.
- **Between turns**: update one box at a time. A partially complete
  file is better than a stale one.
- **On completion**: move every item to Done and leave a final
  "Complete" note at the top.

Do not use this skill as a substitute for the agent's own
scratchpad / working memory — it is for user-visible task tracking.
