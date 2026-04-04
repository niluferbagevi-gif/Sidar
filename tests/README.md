# Test Layout

This directory follows a test pyramid layout:

- `unit/`: fast tests with mocks only
- `integration/`: cross-module tests
- `e2e/`: end-to-end user flows
- `performance/`: benchmark and load-oriented tests
- `quality/`: quality gate and static quality checks
- `fixtures/`: shared fake payloads and test assets
