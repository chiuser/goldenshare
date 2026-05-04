# Lake Console UI Review Skill

Use this skill when reviewing `lake_console/frontend` UI quality or planning a small redesign round.

This is a review and planning skill. If the user asks for audit only, do not modify files.

This skill is subordinate to:

1. `lake_console/AGENTS.md`
2. `lake_console/frontend/AGENTS.md`
3. `lake_console/frontend/.skills/lake-console-design-system/SKILL.md`

## Review posture

Review the current code and UI structure before suggesting changes.

Do not recommend:

1. full-site redesign
2. UI framework replacement
3. backend/API changes for a frontend-only issue
4. importing production frontend components
5. one-off visual fixes that create another style branch

Prefer small rounds that improve one page or one repeated pattern.

## Review checklist

Check these items in order.

### 1. Page layout

Verify:

1. the page has one clear `PageHeader`
2. page sections are visually grouped
3. the overview/detail split is respected
4. the sidebar and shell remain consistent
5. the page does not expose design rationale as user-facing copy

Flag:

1. too many unrelated sections on one page
2. detail-heavy lists on overview pages
3. page-specific layout hacks that should become components

### 2. Cards

Verify:

1. `Panel` is used for major sections
2. `Metric` is used for compact numeric facts
3. dataset cards align repeated facts and actions
4. card spacing and density are consistent

Flag:

1. repeated one-off card CSS
2. buttons jumping vertically across cards
3. mismatched card borders, shadows, radii, or backgrounds

### 3. Tables and lists

Verify:

1. tables are used only for comparable row data
2. long partition lists are not shown by default on overview pages
3. dense lists have clear labels and stable spacing

Flag:

1. table-like markup duplicated inside pages
2. very long lists without filtering or drill-down
3. raw file paths overwhelming the main overview

### 4. Badge usage

Verify:

1. status labels use `Badge` or `HealthBadge`
2. badge tones follow the approved mapping
3. category labels use `brand` or `muted`, not custom CSS

Flag:

1. raw styled `span` badges
2. new ad-hoc classes such as `tag` or `status-badge`
3. status colors that conflict with the tone meaning

### 5. Empty, error, and loading states

Verify:

1. loading state is visible when data is not ready
2. empty state tells the user what it means
3. error state uses `.alert.error`
4. unavailable facts are omitted or clearly marked

Flag:

1. silent empty screens
2. frontend-estimated backend facts
3. internal implementation notes shown as UI copy

### 6. CSS hygiene

Verify:

1. tokens come from `src/styles/base.css`
2. raw colors are avoided
3. CSS changes are scoped to the target page or shared component
4. large CSS reorganization is not mixed with feature work

Flag:

1. raw colors without a token reason
2. new random radius or shadow values
3. duplicated component styles

## Recommended first-pass tasks

When a page is messy, choose at most three small tasks:

1. split the page from `main.tsx`
2. extract one or two repeated components
3. normalize badges/states/cards

Do not do more unless the user explicitly approves a larger round.

## Review output format

For audit-only work, output:

1. current UI score out of 10
2. top 5 issues
3. what should not be changed
4. next 3 small tasks
5. expected file impact for each task

For completed redesign work, output:

1. selected page
2. changed files
3. extracted components
4. UI improvements
5. whether behavior/API changed
6. validation results
7. next recommendation
