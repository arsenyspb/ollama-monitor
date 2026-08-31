# AI Co-Development Guidelines

This repository relies on AI-assisted workflows (e.g. LLM coding assistants). To ensure consistency, trackability, and high-quality software development, AI agents should adhere to the following best practices:

## 1. Issue-Driven Development
- **Create Issues for Work Items:** For any planned feature, bug fix, or refactoring, always create a GitHub Issue first. This serves as a durable record of intent.
- **Use Checklists:** Break down the work into checklists within the issue description. This allows humans and AI agents to track progress incrementally.

## 2. Pull Request (PR) Workflow
- **Well-Defined PRs:** AI agents must commit code via Pull Requests rather than pushing directly to the `main` branch.
- **Link PRs to Issues:** Every PR should explicitly reference the source issue it resolves (e.g. `Resolves #123`).
- **Strike off Checklists:** As features are implemented, update the source issue's checklist.
- **Explain Changes:** The PR description should clearly explain the "Why" and "What" of the changes, especially if architectural decisions were made autonomously by the AI.

## 3. Continuous Integration / Continuous Deployment (CI/CD)
- **Ensure Green Builds:** An AI agent must monitor and verify that all CI/CD pipelines (e.g. tests, linters, builds) pass cleanly on its PR before requesting human review or merging.
- **Test-Driven:** Whenever adding new logic, include corresponding unit or integration tests to prove correctness and prevent regressions.

## 4. Known Architectural Constraints
- **Ollama Metrics (TPS):** Ollama does not log generation statistics (`eval_count`, `eval_duration`) to the background `server.log` by default. These stats are only emitted in the JSON responses to API clients. Passive log tailing cannot capture background TPS. Future iterations require an active network proxy on port `11434` to intercept and parse HTTP responses for continuous monitoring of inference speeds.

By following these practices, we maintain a secure, observable, and maintainable codebase alongside our AI collaborators.