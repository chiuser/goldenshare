---
name: "本地部署技能"
description: "Use when the user asks to compile and start Goldenshare locally (Web + frontend dev), or debug local startup flow."
---

# Goldenshare Local Build Run Skill

## When to use
- User asks to start local dev environment quickly.
- User asks for one-command local compile + run.
- User asks to verify local Web + frontend startup status.
- User asks local startup troubleshooting.

## Must-read context before actions
1. `/Users/congming/github/goldenshare/AGENTS.local.md`
2. `/Users/congming/github/goldenshare/scripts/AGENTS.md`
3. `/Users/congming/github/goldenshare/scripts/local-build-and-run.sh`
4. `/Users/congming/github/goldenshare/docs/release/local-prod-operation-boundary-v1.md`

## Default command (recommended)

```bash
bash scripts/local-build-and-run.sh
```

## Common modes

### Mode A: Full local startup (default)
Use when user says “本地编译启动 / 本地跑起来 / 一键启动”:

```bash
bash scripts/local-build-and-run.sh
```

### Mode B: Web only
Use when user only needs backend API:

```bash
bash scripts/local-build-and-run.sh --web-only
```

### Mode C: Frontend only
Use when user only needs frontend hot reload:

```bash
bash scripts/local-build-and-run.sh --frontend-only
```

### Mode D: With preflight
Use when user wants stronger local checks before startup:

```bash
bash scripts/local-build-and-run.sh --with-preflight
```

## Startup behavior summary
- Backend compile check: `compileall`
- Frontend build check: `npm --prefix frontend run build`
- Start Web: `python3 -m src.app.web.run`
- Start frontend dev: `npm --prefix frontend run dev`

## Verification checklist
1. Web reachable: `http://127.0.0.1:8000/api/health`
2. API docs reachable: `http://127.0.0.1:8000/api/docs`
3. Frontend dev reachable: `http://127.0.0.1:5173/app/`

## Guardrails
- Local mode is for UI/API validation; avoid local bulk write operations.
- Do NOT start local worker/scheduler for production-like batch writes.
- Keep commands aligned with `AGENTS.local.md` boundary rules.

## Expected final report to user
- Command executed
- Which services started (web/frontend)
- Access URLs
- Any startup error and minimal fix
