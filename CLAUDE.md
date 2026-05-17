# Claim Reversal — CLAUDE.md

Multi-agent clinical denial reversal system. Learning project for CrewAI + LangGraph + A2A + MCP + SSE patterns.

---

## Architecture

```
Browser (index.html)       ← SSE timeline + HITL decision card
        │ POST /appeal, GET /stream/{id}, POST /appeal/{id}/resume
Main App (:8000)           ← FastAPI + CrewAI Crew orchestrator
        │ A2A delegation
Evidence Agent (:8001)     ← FastAPI A2A server + LangGraph (HITL via interrupt())
        │
MCP Server (:8002)         ← Shared tools: guideline lookup, payer rules, audit log, claim history
```

CrewAI crew runs sequentially: Intake → Evidence (A2A) → Writer → Physician → Submission.

## Tech Stack

| Layer | Tech |
|---|---|
| Orchestration | CrewAI (`crewai[a2a]`) |
| Evidence agent | LangGraph (standalone, no LangChain) |
| Remote protocol | A2A (protocol v0.3) via CrewAI `A2AClientConfig`/`A2AServerConfig` |
| Shared tools | MCP server (`mcp` SDK, SSE transport) |
| API | FastAPI + uvicorn |
| Frontend | Single HTML file, vanilla JS, EventSource SSE |
| LLM routing | OpenRouter — `openai/gpt-5-mini` (agents), `google/gemini-3.1-flash-lite` (mocks) |
| Database | SQLite — `claims.db`, `events.db` |
| Packaging | `uv`, Docker Compose |

## Environment

```
OPENROUTER_API_KEY=
OPENROUTER_AGENT_MODEL=openai/gpt-5-mini
OPENROUTER_MOCK_MODEL=google/gemini-3.1-flash-lite
MAIN_APP_PORT=8000
EVIDENCE_AGENT_PORT=8001
MCP_SERVER_PORT=8002
HITL_TIMEOUT_SECONDS=300
USE_PLAYWRIGHT=false
```

Swap models via env vars only. Never hardcode model names or ports.

---

## Documentation Hierarchy

| Document | Purpose |
|---|---|
| `01.clinical-denial-reversal-spec.md` | Business workflow — actors, steps, decision points |
| `02.clinical-denial-reversal-tech-spec.md` | Architecture — agents, schemas, contracts, build phases. No implementation code |
| `03.*.md` (future) | Implementation guides — step-by-step code per phase |

Tech spec describes **what** to build. Implementation guides describe **how**.

---

## Key Design Decisions

- **CrewAI** for sequential orchestration; **LangGraph** only where branching + HITL exist (Evidence agent)
- **A2A** for the Evidence agent — simulates organizational boundary; `fail_fast=False` for graceful degradation
- **MCP SSE** for shared tools — SSE transport is legacy but still supported by `mcp>=1.27` and CrewAI
- **One HITL point** — evidence sufficiency only; physician sign-off and escalation are simulated
- **All data mocked** — LLM-generated (cached to disk) or hardcoded; no real EMR/payer integration

## Development Environment

- Windows 11 + Git Bash (MINGW64) — all shell commands use Unix syntax
- Python ≥ 3.12; command is `python`, not `python3`
- Virtual environment: `source .venv/Scripts/activate`
- Three terminals: MCP (:8002) → Evidence A2A (:8001) → Main App (:8000)

## Coding Standards

- Every file starts with `# <relative-path>` (e.g. `# a2a_server/graph.py`).
- Every function/method gets a single-line docstring explaining its purpose.
- Inline `#` comments on conditional branches, routing logic, and non-obvious decisions. Not on obvious assignments or imports.
- Type-annotate all function signatures. Pydantic models at service boundaries — no raw `dict` in/out.
- `asyncio.Queue` for SSE event passing. `httpx.AsyncClient` for outbound HTTP.
- CORS middleware required for local dev (frontend on different port).

## Approach

- When analyzing problems, always start with clarifying questions if the request is ambiguous, don't make assumptions.
- Push back when it makes sense and provide evidence, reasoning.
- Think before acting. Read existing files before writing code.
- Prefer editing over rewriting whole files.
- Test your code before declaring done.
- No sycophantic openers or closing fluff.
- Keep solutions simple and direct.
- User instructions always override this file.
