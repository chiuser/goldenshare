# AGENTS.md - market homepage rules

## Scope

This directory contains the first mocked market homepage for the business quote system.

## Rules

- Restore the V10 prototype visual language first. Do not redesign the page.
- Keep all data mocked in local files until the business API contract is explicitly reviewed.
- Keep V10 dark-market styles scoped under `.market-page` so they do not leak into Ops pages.
- Use A-share color semantics: red means rising, green means falling.
- Keep page orchestration in `market-homepage-page.tsx`; keep static mock structures in `market-homepage-data.ts`.
- New real API wiring must be planned separately and must not be mixed into this mock prototype page.
