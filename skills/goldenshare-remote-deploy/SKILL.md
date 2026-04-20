---
name: "远程部署技能"
description: "Use when the user asks to deploy, restart, or verify Goldenshare services on the remote production server."
---

# Goldenshare Remote Deploy Skill

## When to use
- User asks to deploy/release to remote server.
- User asks to restart web/worker/scheduler services.
- User asks to verify remote deployment health/state.
- User asks why deploy script fails on remote.

## Must-read context before actions
1. `/Users/congming/github/goldenshare/AGENTS.local.md`
2. `/Users/congming/github/goldenshare/scripts/AGENTS.md`
3. `/Users/congming/github/goldenshare/scripts/deploy-systemd.sh`
4. `/Users/congming/github/goldenshare/scripts/deploy-layered-systemd.sh`

## Deployment defaults
- Prefer SSH alias: `goldenshare-prod`
- Remote repo: `/opt/goldenshare/goldenshare`
- Run deploy as user `goldenshare` (avoid git ownership issues)
- Main command:

```bash
ssh goldenshare-prod 'sudo -n -u goldenshare /bin/bash -lc "cd /opt/goldenshare/goldenshare && bash scripts/deploy-systemd.sh dev-interface"'
```

## Operation modes
### Mode A: deploy + verify (default)
- Use when user says "发版/部署/上线/发布"
- Execute full deploy flow, then run verification checklist.

### Mode B: verify only (no deploy)
- Use when user says "只验收/只检查/不发版只看状态"
- Must NOT run pull/install/restart/deploy script.
- Only run health/state verification:

```bash
ssh goldenshare-prod 'systemctl is-active goldenshare-web.service && systemctl is-active goldenshare-ops-worker.service && systemctl is-active goldenshare-ops-scheduler.service'
ssh goldenshare-prod 'systemctl cat goldenshare-web.service | grep -n ExecStart'
ssh goldenshare-prod 'curl -s http://127.0.0.1:8000/api/health'
ssh goldenshare-prod 'curl -s http://127.0.0.1:8000/api/v1/health'
```

## Safe execution checklist
1. Confirm remote branch and head.
2. Confirm sudo whitelist is valid for deploy user.
3. Run deploy script (main command above).
4. Verify all services are active:
   - `goldenshare-web.service`
   - `goldenshare-ops-worker.service`
   - `goldenshare-ops-scheduler.service`
5. Verify web unit entrypoint:
   - `ExecStart` should be `python -m src.app.web.run`
6. Verify API health:
   - `/api/health`
   - `/api/v1/health`

## Unit sync rule (important)
- If any file below changed, ensure sync to `/etc/systemd/system` and reload daemon:
  - `scripts/goldenshare-web.service`
  - `scripts/goldenshare-ops-worker.service`
  - `scripts/goldenshare-ops-scheduler.service`
- Follow repo rule in `/Users/congming/github/goldenshare/scripts/AGENTS.md`.

## Guardrails
- Do not edit unrelated services.
- Do not skip post-deploy health checks.
- Do not use interactive sudo in automation commands.
- Keep behavior compatible: deploy script remains the primary orchestrator.

## Troubleshooting quick map
- `sudo: a password is required`:
  - check `/etc/sudoers.d/goldenshare-deploy` and `sudo -n -l` for `goldenshare`.
- deploy fails at web unit check:
  - verify `systemctl cat goldenshare-web.service` permission is whitelisted.
- deploy succeeds but entrypoint still old:
  - ensure unit sync happened and daemon-reload executed.

## Expected final report to user
- Command executed
- Service status summary (3 services)
- Web entrypoint check result
- Health endpoint check result
- Any residual risk and next action
