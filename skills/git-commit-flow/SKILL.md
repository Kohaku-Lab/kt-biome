---
name: git-commit-flow
description: Safe conventional-commit workflow for an agent asked to commit changes. Run tests before staging, stage deliberately, write a Conventional Commits-style subject + body, never amend or force-push without explicit user approval.
license: KohakuTerrarium License 1.0
paths:
  - "*.py"
  - "*.ts"
  - "*.tsx"
  - "*.js"
  - "*.jsx"
  - "*.go"
  - "*.rs"
---

# git-commit-flow

Use this skill any time the user asks for a commit ("commit", "check
this in", "push a patch"). The goal is a reviewable atomic commit with
a message that matches the repository's conventions — not a best-effort
`git commit -am "wip"`.

## Preflight

1. Run `git status` + `git diff` to confirm you know exactly what will
   be staged. Never run `git add -A` blind.
2. Run the repository's test command (check `package.json`,
   `pyproject.toml`, `Makefile`, or ask if unsure). Block on failures
   unless the user explicitly says "commit anyway".
3. If the diff contains secrets, `.env` files, or binary blobs, stop
   and flag it to the user before staging.

## Staging

4. `git add <paths>` — stage files individually or by glob. Avoid
   `-A` / `.` so unrelated dirty files don't hitch-hike into the
   commit.
5. Re-run `git status` to confirm only intended files are staged.

## Message format (Conventional Commits)

6. Subject line: `<type>(<scope>)?: <subject>` where `type ∈ {feat,
   fix, refactor, test, docs, chore, perf, build, ci}`. Keep the
   subject under 72 chars.
7. Leave the body blank for trivial commits. For non-trivial ones, add
   a blank line + 2-5 bullet points explaining *why*, not *what*.
8. Never sign off as somebody else. Never fabricate a
   `Co-Authored-By:` line.

## Hard rules

- **Never** run `git reset --hard`, `git push --force`, or pass
  `--no-verify`/`--no-gpg-sign` without explicit user approval.
- **Never** amend a commit the user has already pushed.
- **Never** create a new commit when the user only asked you to
  review a diff.
