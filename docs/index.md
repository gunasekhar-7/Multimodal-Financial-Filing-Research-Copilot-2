# Project documentation

Use these guides to understand, run, and extend the Financial Filing Research Copilot.

## Learn by doing

- [Run the offline demo](tutorial-local.md) — create an isolated environment, seed deterministic demo data, start the web app, and generate a report.

## Solve a task

- [How-to guides](how-to.md) — configure SEC structured-facts mode, run tests and evaluation, use Docker Compose, regenerate the golden dataset, and troubleshoot common issues.
- [Contributing](../CONTRIBUTING.md) — development conventions and the review checklist.

## Look up a detail

- [Technical reference](reference.md) — HTTP endpoints, request and response models, settings, scripts, database behavior, and CI checks.

## Understand the design

- [Architecture and design](architecture.md) — system context, data flow, retrieval and verification decisions, trust boundaries, limitations, and a prioritized future scope.
- [Repository architecture overview](../ARCHITECTURE.md) — concise component map.

## Source of truth

Documentation describes the behavior implemented in this repository. The offline demo is synthetic; only the opt-in ingestion path reads SEC Company Facts. SEC filing text, semantic entailment, authentication, and horizontally coordinated hosting are not implemented. See [limitations and future scope](architecture.md#limitations-and-trust-boundaries) before interpreting a report or planning deployment.
