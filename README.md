# kohaku-creatures

Default creatures and terrariums for [KohakuTerrarium](https://github.com/Kohaku-Lab/KohakuTerrarium).

## Install

```bash
# Install as a KohakuTerrarium package
kt install https://github.com/Kohaku-Lab/kohaku-creatures.git

# Or install as editable (for development)
kt install ./kohaku-creatures -e
```

## Creatures

| Name | Description | Base |
|------|-------------|------|
| `general` | Base creature: 19 tools, 6 sub-agents, core personality | (none) |
| `swe` | Software engineering specialist | general |
| `reviewer` | Code review specialist | general |
| `ops` | Infrastructure and operations specialist | general |
| `researcher` | Research and analysis specialist | general |
| `creative` | Creative writing specialist | general |
| `root` | Terrarium management, task delegation | general |

## Terrariums

| Name | Description | Creatures |
|------|-------------|-----------|
| `swe_team` | SWE team with root agent | root, swe, reviewer |

## Usage

```bash
# Run a creature directly
kt run @kohaku-creatures/creatures/swe

# Run a terrarium
kt terrarium run @kohaku-creatures/terrariums/swe_team

# Edit a creature config
kt edit @kohaku-creatures/creatures/general
```

## Creating Your Own Package

A creature/terrarium package is a directory with:

```
my-package/
  kohaku.yaml          # manifest (name, version, creatures, terrariums)
  creatures/
    my-agent/
      config.yaml      # agent config (can use base_config: "@other-package/...")
      prompts/
        system.md
  terrariums/
    my-team/
      terrarium.yaml
```

The `kohaku.yaml` manifest:

```yaml
name: my-package
version: "1.0.0"
description: "My custom agents"

creatures:
  - name: my-agent
    path: creatures/my-agent
    description: "A custom agent"
    base: "@kohaku-creatures/creatures/general"

terrariums:
  - name: my-team
    path: terrariums/my-team
    description: "My team setup"
```

Cross-package references use `@package-name/path` syntax:

```yaml
# In your creature's config.yaml
base_config: "@kohaku-creatures/creatures/swe"
```

## License

KohakuTerrarium License 1.0 (see [LICENSE](https://github.com/Kohaku-Lab/KohakuTerrarium/blob/main/LICENSE))
