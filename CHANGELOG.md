# Changelog

## 4.0.0

Requires KohakuTerrarium >2.1.7,<3.0.0.

### Breaking changes

- General, SWE, and researcher creatures expose only the lightweight task
  sub-agents `explore` and `critic`. The inherited `worker` and `plan` entries
  have been removed.
- The framework also removes the builtin `research` and `coordinator` presets.
  Assign substantial implementation, research, or coordination work to graph
  creatures, or define an application-specific custom sub-agent.
- Inspection helpers have no shell access. Supply a diff for change reviews and
  relevant requirements explicitly; they do not see the parent conversation.

### Inspection defaults

- `explore` answers bounded workspace questions with file evidence and gaps.
- `critic` reviews specified artifacts for concrete defects without fixing them
  or running test suites. No findings within the reviewed scope is a valid result.
- Both use `read`, `glob`, `grep`, and `tree`, with 8/12 soft/hard model-call
  budgets, 24/40 tool-call budgets, a 14-call absolute cap, and a 600-second
  emergency timeout. Neither preset enables automatic compaction.
- `critic` inherits the parent model; `explore` uses the configured sub-agent
  model mapping or the parent as fallback.

### Upgrade notes

Use a KT nightly containing the inspection-helper changes or a later stable
release satisfying >2.1.7,<3.0.0. KT warns and skips unknown or removed builtin
sub-agent config entries, including in strict mode,
so updating KT before an older kt-biome installation does not prevent startup.
Remove stale delegation instructions from downstream configurations.

Service presets `response`, `summarize`, `memory_read`, and `memory_write` remain
available in KT with unchanged defaults. They are not automatically enabled by
these creature presets. The parent retains overall planning and decisions.

The package manifest and Python distribution metadata now both report 4.0.0.
