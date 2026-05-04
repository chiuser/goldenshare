# Lake Console Design System Skill

Use this skill when changing `lake_console/frontend` UI structure, visual styling, or shared components.

This skill is subordinate to:

1. `lake_console/AGENTS.md`
2. `lake_console/frontend/AGENTS.md`

It must not weaken lake console isolation rules, introduce a new UI framework, or turn legacy design documents into the highest constraint.

## Current design baseline

The current verified UI direction is:

1. professional local data operations console
2. calm and low-noise
3. dense but readable
4. file-fact oriented
5. no marketing-page styling
6. no flashy big-screen dashboard styling

The codebase already has these shared primitives:

1. `PageHeader`
2. `Panel`
3. `Metric`
4. `Badge`
5. `HealthBadge`
6. `EmptyState`

Prefer these before creating new components.

## Page layout rules

Use the existing shell:

1. product header
2. sidebar navigation
3. main content area
4. page-level `PageHeader`
5. grouped page sections

Overview pages should answer:

1. What exists?
2. What is the current coverage?
3. Is anything risky?
4. Where can the user drill down?

Detail pages should answer:

1. What does this dataset currently contain?
2. Which layers exist?
3. Where are the files?
4. What are the ranges, sizes, counts, and risks?

Do not overload overview pages with long operational detail.

## Card rules

Use `Panel` for major sections and `Metric` for summary facts.

Dataset cards should:

1. keep source, title, status, key, description, coverage, file facts, and action aligned
2. keep action buttons in a stable position
3. use the same fact order across cards
4. avoid one-off shadows, borders, radii, and background colors

Detail facts should use key-value grids or structured rows, not prose blocks.

## Table and list rules

Only introduce a table when the rows are meant to be compared.

If a new table-like section is needed, create or reuse a `DataTableCard`-style component rather than writing table styling inline in the page.

Partition data should not become a long default list on overview pages. Prefer summarized count, size, date/month range, latest update, and risk. Put deeper inspection behind a detail page or explicit drill-down.

## Badge rules

All status labels use `Badge` or `HealthBadge`.

Tone mapping:

1. `success`: ok, initialized, ready, written
2. `warning`: waiting, partial, degraded, risk
3. `error`: error, failed, critical
4. `muted`: secondary metadata or counts
5. `brand`: command scenarios, categories, non-status labels

Do not add ad-hoc badge classes such as `tag` or `status-badge`.

If a page needs a new label style, first try to express it with an existing tone.

## State rules

Every page or async panel must make these states explicit:

1. loading
2. empty
3. error
4. ready

Use `EmptyState` for empty/loading-like neutral states when no dedicated loading component exists.

Use `.alert.error` for API errors.

Do not display internal design rationale in the UI. Put rationale in docs or AGENTS files.

Do not invent backend facts in the frontend.

## CSS rules

Use tokens from `src/styles/base.css`.

Do not add raw colors when an existing token fits.

Do not split or reorganize large CSS blocks together with unrelated feature work.

CSS splitting should be incremental:

1. base tokens/reset first
2. reusable components next
3. page-specific styles last

## Prohibited

Do not:

1. introduce AntD, MUI, shadcn/ui, Tailwind, Chakra, or another primary UI framework
2. import production `frontend/src/**`
3. import production `src/ops/**`, `src/app/**`, or production APIs as a shortcut
4. make frontend pages synthesize dataset status or file facts
5. create a new visual style for each page
6. use neon, heavy glassmorphism, big-screen dashboard, or marketing hero styling
7. combine backend/API changes with UI-only redesign work

## Required validation

After meaningful frontend UI changes, inspect `package.json` and run available scripts.

At minimum, currently run:

```bash
cd lake_console/frontend
npm run build
```

If `typecheck`, `test`, or `lint` scripts are added later, run them too.
