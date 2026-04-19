# Customer Support Triage Voice Agent

A voice-agent demo for customer support triage. An ElevenLabs agent handles inbound web-widget calls, classifies the caller's intent (billing, technical, account change, cancellation, other), and extracts structured fields via the platform's built-in Data Collection analysis. A post-call webhook fires to a FastAPI backend, which verifies the HMAC signature, persists a ticket row to Postgres, and exposes a public read-only `/tickets` dashboard.

> **Status**: in active development. This README will be expanded with a try-it link, architecture diagram, tech-choice rationale, test matrix, and Loom walkthrough before v1.0.

## Planning documents

Decisions, design rationale, and the operator setup checklist live in:

- [PLAN.md](PLAN.md) - architecture and design (why the pieces fit together this way)
- [RUNBOOK.md](RUNBOOK.md) - linear operator setup checklist (signup, provisioning, deploy)
- [docs/data-collection-schema.md](docs/data-collection-schema.md) - Data Collection field spec (the agent's extraction contract)

## Tech stack

Python 3.11+ - FastAPI - SQLAlchemy + Postgres - Jinja2 - ElevenLabs SDK - Railway - uv.

## License

See [LICENSE](LICENSE) if present; otherwise all rights reserved pending first release.
