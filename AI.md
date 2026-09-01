# AI Co-Development Guidelines

This repository relies on AI-assisted workflows (e.g. LLM coding assistants). To ensure consistency, trackability, and high-quality software development, AI agents should adhere to the following best practices:

## 1. Issue-Driven Development
- **Create Canonical Issues:** All features, bug fixes, and improvements MUST follow a canonical GitHub Issue. This issue must be detail-oriented, include a step-by-step checklist, and explicitly assert TDD (Test-Driven Development) requirements.
- **Preserve AI Reasoning:** Ensure the state of your (or any AI agent's) reasoning (why a specific architectural path or technical approach was chosen over others) is thoroughly documented within the issue so context is never lost for the next agent or human.
- **Use Checklists:** Break down the work into checklists within the issue description in a logical, order-dependent sequence so another agent can pick it up.

## 2. Pull Request (PR) Workflow
- **Well-Defined PRs:** AI agents must commit code via Pull Requests rather than pushing directly to the `main` branch.
- **Link PRs to Issues:** Fixes for issues MUST be submitted as PRs with a direct mention of the canonical issue it fixes (e.g. `Resolves #123`) to ensure traceability.
- **Strike off Checklists:** As features are implemented, update the source issue's checklist.
- **Explain Changes:** The PR description should clearly explain the "Why" and "What" of the changes, especially if architectural decisions were made autonomously by the AI.

## 3. Continuous Integration / Continuous Deployment (CI/CD)
- **Ensure Green Builds:** An AI agent must monitor and verify that all CI/CD pipelines (e.g. tests, linters, builds) pass cleanly on its PR before requesting human review or merging.
- **Test-Driven:** Whenever adding new logic, include corresponding unit or integration tests to prove correctness and prevent regressions.

## 4. Known Architectural Constraints
- **Ollama Metrics (TPS):** Ollama does not log generation statistics (`eval_count`, `eval_duration`) to the background `server.log` by default. These stats are only emitted in the JSON responses to API clients. Passive log tailing cannot capture background TPS. Future iterations require an active network proxy on port `11434` to intercept and parse HTTP responses for continuous monitoring of inference speeds.

By following these practices, we maintain a secure, observable, and maintainable codebase alongside our AI collaborators.