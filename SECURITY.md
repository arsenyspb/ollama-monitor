# Security Policy

## Reporting a vulnerability

Do not open a public issue for security problems. Report privately through GitHub's "Report a vulnerability" button on the repository's Security tab, or contact the repository owner directly.

## Scope and trust boundaries

- **Local services.** The TPS proxy listens on port `11434` and forwards to Ollama on `11435`. Neither port should be exposed beyond localhost.
- **Privileged operations.** Monitor and proxy targets in the `Makefile` use `sudo`, edit systemd or `launchctl` configuration, and restart Ollama. Review them before running.
- **Automation.** Labels named `flow:*` forward issues to an external orchestrator. Only the repository owner may apply them. Issue and PR text is untrusted input for any automated agent.
- **Secrets.** Repository secrets, including the flow dispatch token, live in GitHub Actions secrets. They must never be committed or printed in logs.
