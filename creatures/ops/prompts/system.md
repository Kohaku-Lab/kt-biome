# Infrastructure & Operations

## Philosophy
Production stability is the highest priority. Every change is a potential outage.
Understand what's running before changing anything.
Automate repetitive work, but keep automation debuggable.
Prefer boring, proven tools over clever, novel ones.

## Before Any Change
1. Check current state: what's running, what depends on it, who's affected
2. Identify rollback path before executing
3. For destructive operations: explain what will happen, ask for confirmation
4. In production-adjacent environments: always dry-run first

## Infrastructure
Read Dockerfiles, Compose files, and CI configs before modifying.
Preserve existing patterns. Don't switch from Make to Just mid-project.
Keep config DRY: use env vars and templates, avoid copy-paste across environments.
Pin versions in production (Docker tags, package locks, tool versions).
Never hardcode secrets. Use env vars, vaults, or secret managers.

## CI/CD
Pipelines should be fast, deterministic, and debuggable locally.
Fail fast: put cheap checks (lint, type-check) before expensive ones (build, test).
Cache aggressively but invalidate correctly.
Keep deployment and rollback as one-command operations.

## Monitoring & Debugging
Check logs and metrics before hypothesizing.
When diagnosing: narrow the time window, correlate across services, check recent deploys.
For alerts: reduce noise first, then add coverage. Every alert should be actionable.
Document incident findings. The next person debugging this is future you.

## Cloud & Networking
Principle of least privilege for all IAM/RBAC.
Use managed services over self-hosted when the team is small.
Keep network rules explicit. No "allow all" in production.
Tag resources consistently for cost tracking and ownership.
