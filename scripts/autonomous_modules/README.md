# Autonomous loop modules

`autonomous_loop.sh` remains the public entry point and owns configuration
normalization, preflight ordering, retry bounds, and final loop control. Focused
domain operations are sourced from this directory:

- `coverage_agent.sh`: bounded CoverageAgent analysis, ReviewerAgent semantic gate, rejection-state tracking, and missing-test generation.
- `auto_heal.sh`: test/static-analysis failure logs to `scripts.auto_heal` handoff, including HITL argument handling.
- `static_analysis.sh`: mypy and Bandit phases plus their scoped auto-heal escalation.

The modules are sourced libraries rather than standalone commands. They consume the
validated globals owned by `autonomous_loop.sh`; new orchestration and retry policy
belongs in the entry point, while domain-specific behavior belongs in the matching
module.
