---
name: goldenshare-doc-governance
description: Use for Goldenshare documentation inventory, document-to-code reconciliation, stale or duplicate document audits, status and authority checks, and narrow documentation cleanup. Default to read-only reporting for one document group; do not treat plans or historical records as current implementation.
---

# Goldenshare Document Governance

Use this skill when the task is to understand, audit, reconcile, organize, or
narrowly clean up Goldenshare project documentation. The default result is an
evidence-backed report, not a bulk rewrite.

## V1 scope

This skill covers only:

1. Inventorying a specified documentation group.
2. Classifying document type, status, authority, and scope.
3. Checking important claims against current project evidence.
4. Finding stale status, duplicated rules, unclear authority, broken references,
   and unresolved decision boundaries.
5. Running the existing documentation integrity check.
6. Producing a concise Garden Report with findings, evidence, suggested action,
   and residual risk.

It does not create a second documentation system, generate an Obsidian vault,
install hooks, build a persistent document database, or scan and rewrite the
whole repository by default.

## Required context

Before auditing, read:

1. The repository root `AGENTS.md`.
2. `docs/AGENTS.md`.
3. The nearest `AGENTS.md` for the target document group, when present.
4. `docs/README.md` and the relevant governance baseline when the task covers
   document structure or indexing.

If the task concerns a specific subsystem, read the current code and tests that
the document claims to describe. Do not infer current behavior from filenames,
document titles, old plans, or chat history.

## Scope boundary

One pass has one clear document group, such as `architecture`, `ops`,
`datasets`, `frontend`, `sources`, or `governance`. A wider audit requires an
explicit scope and should be split into separate group reports.

The existing `docs/` directory is the project documentation root. Do not create
`.openplan/`, `docs-vault/`, a parallel catalog, or another source-of-truth
surface unless the user explicitly approves a separate design.

## Authority model

"Authority" means the evidence that should be accepted for a particular kind
of claim when sources disagree. No single source is authoritative for every
claim.

| Claim type | Default authority | Role of documentation |
|---|---|---|
| Current runtime behavior | Current code, tests, configuration, migrations, and bounded read-only runtime evidence | Describe the verified behavior and its evidence |
| Current API or data contract | Implemented schemas/services plus contract tests and current consumers | State the contract; do not let a page or plan invent fields |
| Adopted architecture or policy | Explicit user decision and the current baseline/decision document | State intent and rationale; verify implementation separately |
| External source behavior | Local source documentation plus current source validation or measured evidence when required | Preserve source semantics, not internal implementation decisions |
| Historical execution or audit | The dated report, commit, log, or snapshot itself | Describe only what was true at that time |
| Agent inference or recommendation | Not authoritative until explicitly accepted | Label as inference, proposal, or pending decision |

When sources conflict:

1. Separate the code fact, document claim, and desired future intent.
2. Report the conflict and its scope.
3. Do not silently change code, silently rewrite the document, or promote an
   inference to project policy.
4. Ask for a decision only when the conflict changes durable intent or behavior.

## Evidence workflow

1. State the audit goal, document root, target group, and non-goals.
2. Inventory only the target group and its direct index or cross-references.
3. Classify each relevant document:
   - `current`: current rule, contract, or baseline;
   - `proposed`: design awaiting confirmation;
   - `implemented-pending-validation`: code exists but acceptance is incomplete;
   - `historical`: dated execution or point-in-time evidence;
   - `superseded`: replaced by a named document or decision;
   - `audit`: scoped evidence report, not a governing contract;
   - `source`: external interface facts.
4. For each important current-state claim, record the narrowest evidence path:
   code symbol or route, test, configuration, migration, source document, or
   bounded read-only verification.
5. Check for duplicate rule definitions. Prefer one current baseline and links
   to it; keep specialist documents focused on their own details.
6. Check status words such as "当前", "已实现", "已验收", "待开发", and
   "执行中" against evidence. If status cannot be proven, use a neutral finding
   rather than upgrading or guessing.
7. Run `python3 scripts/check_docs_integrity.py` for the repository docs surface.
   Record what it checked and what it did not prove.
8. Produce the report before proposing edits. If cleanup is explicitly
   authorized, change only the approved group and preserve unrelated worktree
   changes.

For architecture, dependency, shared contract, dispatcher, worker, or service
claims, use the repository's CodeGraph workflow before editing and trace the
relevant entry points, callers/callees, tests, and consumers. Use a narrow
track; do not perform broad exploration without a decision need.

For source-document work, preserve stable paths and indexes. Treat staging and
published source docs as different surfaces, and do not overwrite curated
published documents from a newly captured source set without explicit rules.

## Garden findings

Use these severities:

- `G0`: likely to make a human or agent act incorrectly; wrong authority or
  materially false current behavior.
- `G1`: stale status, missing rationale, unclear decision boundary, or important
  claim without evidence.
- `G2`: duplicated content, weak traceability, incomplete next action, or poor
  zero-context readability.
- `G3`: navigation, naming, wording, or formatting improvement.

Every finding must include:

- document path;
- evidence checked;
- the document claim or structural issue;
- impact;
- suggested action;
- whether human confirmation is required.

## Report contract

Return a concise report with this shape:

```markdown
# Goldenshare Documentation Garden Report

## Scope

## Authority and Evidence

## Findings

### G1: Short title

- Document:
- Evidence checked:
- Finding:
- Impact:
- Suggested action:
- Human confirmation required: yes/no

## Checks Run

## Checks Not Run

## Maintenance Suggestions

## Residual Risk
```

Do not call a scoped report "approval" or "complete". State the reviewed
scope and remaining uncertainty.

## Modification rules

The skill is read-only unless the user explicitly asks for cleanup or a named
document change. When editing is authorized:

1. Reconfirm the target group and exact files before writing.
2. Make the smallest coherent change; do not add unrelated governance.
3. Preserve historical evidence by marking it historical or superseded rather
   than erasing it when its historical value matters.
4. Update `docs/README.md` when adding, removing, or merging an indexed document.
5. Run `python3 scripts/check_docs_integrity.py` and `git diff --check`.
6. Report changed files, boundary impact, validation, residual risk, and next
   work.

Never:

- treat a plan as proof that implementation exists;
- claim production readiness from browser or document evidence alone;
- silently resolve a conflict between a current document and current code;
- bulk-delete, bulk-rewrite, or migrate document roots;
- add repo-scoped Codex hooks or automatic document rewriting;
- modify code, database, Lake, production, or deployment state as part of a
  documentation audit unless the user separately authorizes it.
