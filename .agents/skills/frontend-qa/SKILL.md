---
name: frontend-qa
description: Use for Goldenshare frontend UI, React, Vite, page interaction, layout, browser validation, data pages, API contract consumption, and frontend performance checks under frontend or lake_console/frontend. 适用于前端页面、交互、布局、数据页、浏览器验收和前端性能检查。
---

# Frontend QA

Use this skill for changes under `frontend/**` or `lake_console/frontend/**`.

## Required Context

1. Read the nearest `AGENTS.md`.
2. Read the relevant `package.json`.
3. Inspect existing components, hooks, styles, and service wrappers before changing UI.
4. If the frontend consumes a changed API or contract, audit the backend schema and consumers with CodeGraph or current code.

## Implementation Rules

1. Match the existing design system and local component patterns.
2. Do not create marketing-style pages for operational tools.
3. Data pages, logs, samples, and run histories must use backend pagination, bounded result sets, filters, or virtual scrolling.
4. Text must not overflow buttons, cards, tables, panels, or mobile containers.
5. For unfamiliar icons, use the existing icon library when available and add tooltips where needed.
6. Do not add extra features beyond the user request.

## Verification

For `frontend/**`:

1. Run `npm --prefix frontend run typecheck`.
2. Run `npm --prefix frontend run build`.
3. If layout, interaction, routing, or data loading changed, run browser verification with Browser, Chrome, or Playwright. Include console and network checks.

For `lake_console/frontend/**`:

1. Run `npm --prefix lake_console/frontend run build`.
2. If layout, interaction, routing, or data loading changed, run browser verification with Browser, Chrome, or Playwright. Include console and network checks.

## Delivery Gate

Report changed UI surface, API/contract impact, validation commands, browser findings when applicable, screenshots or routes checked, and remaining risk.

