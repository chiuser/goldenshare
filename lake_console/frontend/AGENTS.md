# lake_console frontend agent guide

## Scope

This guide applies only to:

```text
goldenshare/lake_console/frontend
```

Do not modify the repository-level application at:

```text
goldenshare/frontend
```

unless the user explicitly asks for it.

Do not modify:

```text
lake_console/backend
production src/**
production Ops / Web app code
```

for frontend-only UI tasks.

## Project role

This is the frontend for the goldenshare lake console.

It is a professional local data operations console, not a marketing site, not a flashy big-screen dashboard, and not the final stock trading workspace.

Primary goals:

1. Stable frontend iteration.
2. Better UI quality.
3. Consistent components.
4. Clear page structure.
5. Safe API/data boundaries.
6. No frontend-side invention of backend facts.

## Required reading before work

Before modifying lake console frontend code, read in this order:

```text
1. lake_console/AGENTS.md
2. lake_console/frontend/AGENTS.md
3. lake_console/frontend/.skills/lake-console-design-system/SKILL.md
4. lake_console/frontend/.skills/lake-console-frontend-architecture/SKILL.md
5. lake_console/frontend/.skills/lake-console-ui-review/SKILL.md
6. lake_console/frontend/package.json
7. lake_console/frontend/src
```

If external skills are installed under `.agents/skills`, use relevant ones only after reading the local rules:

```text
.agents/skills/design-taste-frontend/SKILL.md
.agents/skills/minimalist-ui/SKILL.md
.agents/skills/redesign-existing-projects/SKILL.md
```

## Design source priority

When frontend UI rules conflict, use this priority order:

```text
1. lake_console/AGENTS.md
2. lake_console/frontend/AGENTS.md
3. lake_console/frontend/.skills/lake-console-design-system/SKILL.md
4. lake_console/frontend/.skills/lake-console-frontend-architecture/SKILL.md
5. lake_console/frontend/.skills/lake-console-ui-review/SKILL.md
6. current lake_console/frontend source code and existing architecture
7. external taste skills
8. legacy design documents and showcase files
```

## Legacy design documents

The old design documents are not the highest constraint for the current lake console UI optimization.

Treat these files as legacy design baseline, token references, component references, and historical visual assets:

```text
docs/frontend/frontend-design-tokens-and-component-catalog-v1.md
docs/frontend/frontend-component-showcase-v1.html
docs/frontend/frontend-biz_design_system_v13.md
docs/frontend/frontend-biz_component_catalog_v13.md
docs/frontend/frontend-biz_component_showcase_v13.html
```

Allowed:

1. Use their tokens, naming ideas, component categories, density rules, and typography guidance.
2. Use them to understand historical visual direction.
3. Use them as references when building or refactoring local lake console components.

Not required:

1. Pixel-level replication.
2. Exact CSS class copying.
3. Exact layout copying.
4. Preserving old UI choices that are visibly ugly, heavy, inconsistent, or unsuitable for lake console.

If a legacy design document conflicts with this file or local lake console skills, follow this file and the local lake console skills.

## External skills policy

External skills are helpers, not project authority.

Use:

```text
design-taste-frontend
minimalist-ui
redesign-existing-projects
```

only for:

1. diagnosing why an existing page looks bad
2. improving visual hierarchy
3. improving spacing, typography, card structure, table structure, and status presentation
4. guiding small redesign steps
5. reducing generic default-component appearance

Do not let external skills cause:

1. introduction of a second UI framework
2. API semantic changes
3. backend behavior changes
4. frontend-side backend fact inference
5. flashy dashboard / marketing website / neon / heavy glassmorphism style
6. full-site rewrite in one step

## UI direction

The lake console UI should feel:

- professional
- calm
- modern
- dense but readable
- data-platform oriented
- low-noise
- consistent

Good reference qualities:

- Linear-like clarity
- Vercel-dashboard-like restraint
- GitHub-projects-like utility
- professional data platform console structure

Do not copy these products directly. Use them only as quality references.

Avoid:

- random gradients
- heavy glassmorphism
- purple neon dashboard style
- large decorative hero sections
- marketing-site layouts
- excessive whitespace
- inconsistent cards and badges
- raw inline colors when theme/style tokens exist

## UI framework rule

Use the existing UI framework and styling approach already used by this `lake_console/frontend` project.

Do not introduce a second primary UI framework.

Do not add:

- Ant Design
- MUI
- shadcn/ui
- Tailwind
- Chakra
- another design system

unless the user explicitly asks for a separate architecture decision.

## Architecture rules

- Page files should mainly compose layout and feature components.
- Reusable UI should go into shared components.
- Business-specific logic should go into feature modules when the structure supports it.
- API clients, types, and data transformation should not grow uncontrolled inside page files.
- Do not infer backend business facts in page components.
- Do not synthesize dataset status, source identity, latest date, layer snapshot, canonical dataset keys, or task state in the page layer.
- Prefer backend-provided fields and documented API contracts.

## Component direction

Prefer or create reusable components for repeated patterns:

- PageHeader
- PageSection
- SectionCard
- MetricCard
- StatusBadge
- DenseToolbar
- FilterPanel
- DataTableCard
- EmptyStateBlock
- ErrorStateBlock
- LoadingBlock
- DetailKVGrid
- TimelineCard

Do not create a new one-off visual style on every page.

## Page design rules

Every main page should generally have:

1. PageHeader
   - title
   - short description
   - optional breadcrumb
   - optional right-side actions

2. Main content area
   - grouped sections
   - clear visual hierarchy
   - consistent spacing

3. Operational feedback
   - loading state
   - empty state
   - error state

## Redesign workflow

When improving an ugly page:

1. Do not rewrite everything at once.
2. Inspect the existing page first.
3. List at most 5 main UI problems.
4. Identify repeated patterns.
5. Extract one or two reusable components if useful.
6. Apply those components to one target page.
7. Improve hierarchy, spacing, typography, card structure, table structure, and status presentation.
8. Keep API/data behavior unchanged.
9. Run frontend checks.

Do not do "beautify the whole site" in one change.

## Required checks

After meaningful frontend changes, inspect `package.json` and run the available validation commands.

Usually run from this directory:

```bash
cd lake_console/frontend
```

Then run:

```bash
npm run typecheck
npm run test
npm run build
```

If package.json has lint, format, rule check, or smoke test commands, run those too.

If a command does not exist, say so and run the closest available alternative.

## Work report format

For every task, report:

1. Target page or component.
2. Files changed.
3. UI or architecture changes made.
4. Whether behavior/API semantics changed.
5. Whether new dependencies were introduced.
6. Validation commands and results.
7. Remaining risks or recommended next step.
