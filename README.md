# Claim Reversal

Multi-agent system that automates clinical denial reversal in healthcare revenue cycle management. When a payer denies a claim on clinical grounds, the system orchestrates agents to gather evidence, draft an appeal, obtain physician sign-off, and submit — with real-time progress streaming to a browser UI.

**Learning project** for: CrewAI orchestration, LangGraph (conditional branching + HITL), A2A protocol, MCP shared tools, SSE streaming.

## Architecture

```
Browser (index.html)         ← SSE timeline + HITL decision card
        │
Main App (:8000)             ← FastAPI + crew pipeline orchestrator
        │ A2A
Evidence Agent (:8001)       ← LangGraph graph (retry loop + interrupt/resume)
        │
MCP Server (:8002)           ← Shared tools: guideline lookup, payer rules, audit log
```

Pipeline: **Intake → Evidence (A2A) → Writer → Physician → Submission**

## Quick Start

```bash
# Prerequisites: Python >= 3.12, uv
source .venv/Scripts/activate  # Git Bash on Windows

# Install
uv sync

# Configure
cp .env.example .env  # Add your OPENROUTER_API_KEY

# Run (3 terminals)
python mcp_server/server.py                      # Terminal 1
uvicorn a2a_server.app:app --port 8001 --reload  # Terminal 2
uvicorn main:app --port 8000 --reload            # Terminal 3

# Open frontend
# http://localhost:5500 (python -m http.server 5500 in frontend/)
# or open frontend/index.html directly
```

## Test Claims

| Claim ID | Patient | Scenario |
|---|---|---|
| `CLM-2026-00123` | Maria Santos (pneumonia) | Evidence sufficient on first try — full happy path |
| `CLM-2026-00199` | James Chen (knee replacement) | Evidence insufficient — triggers HITL decision |

## Key Patterns Demonstrated

- **CrewAI** — Agent definitions with role/goal metadata; manual pipeline for orchestration control
- **LangGraph** — StateGraph with conditional edges, retry loop, `interrupt()` for HITL suspend/resume
- **A2A** — Evidence agent as standalone service; task lifecycle handles HITL signaling
- **MCP** — Shared tools (SSE transport) consumed by multiple agents across processes
- **SSE** — Real-time event streaming from backend to browser; `asyncio.Queue` per claim

## Project Structure

```
main.py              # FastAPI app, SSE endpoint, crew kickoff
crew/                # Pipeline orchestrator (A2A + HITL + SSE emission)
agents/              # CrewAI agent definitions
a2a_server/          # Clinical Evidence Agent (LangGraph + FastAPI)
mcp_server/          # Shared MCP tools (guideline, payer rules, audit log)
tools/               # Local tool implementations
shared/              # Pydantic models, DB, events, LLM helper
data/                # Mock fixtures + SQLite DB
frontend/            # Single-file vanilla JS UI
tests/               # Unit + integration tests (66+ cases)
_docs/               # Specs and implementation guides
```

## Tests

```bash
# All non-LLM tests (no API key needed)
pytest tests/ -m "not llm" -v

# Full suite (requires OPENROUTER_API_KEY + running A2A server)
pytest tests/ -v
```

## Environment Variables

```
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_AGENT_MODEL=openai/gpt-5-mini
MAIN_APP_PORT=8000
EVIDENCE_AGENT_PORT=8001
MCP_SERVER_PORT=8002
HITL_TIMEOUT_SECONDS=300
USE_PLAYWRIGHT=false
```

## Documentation

- [`_docs/01.clinical-denial-reversal-spec.md`](_docs/01.clinical-denial-reversal-spec.md) — Business workflow
- [`_docs/02.clinical-denial-reversal-tech-spec.md`](_docs/02.clinical-denial-reversal-tech-spec.md) — Technical architecture
- [`_docs/03a-d.implementation-guide-phase*.md`](_docs/) — Build guides per phase
