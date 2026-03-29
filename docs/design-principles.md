# Goldenshare Design Principles

## Purpose

This document defines the architectural rules and engineering principles for `goldenshare`.

It is not a loose reference. It is the default decision framework for future development.

When we add new features, new tables, new APIs, new pages, or new workflows, we should first check whether the design follows the rules in this document. If we intentionally break a rule, we should document why and how we plan to converge back later.

## System Positioning

`goldenshare` is built in two major layers:

1. A market data foundation
2. A future web application platform built on top of that foundation

The market data foundation remains the system of record for ingestion, normalization, operational tracking, and analytical read models.

The web application is an application layer and BFF layer on top of the foundation. It is not allowed to reshape the data foundation around temporary page needs.

## External Reference Rule

External projects may be used as references for:

- page structure
- interaction patterns
- layout details
- user flow ideas

External projects must not be used as architectural references for:

- backend layering
- database naming
- routing structure
- API contract design
- scheduler design
- schema organization
- service boundaries

We do not design `goldenshare` to be compatible with an external repository.

## Layering Principles

The system is organized into these layers and schemas:

- `raw`: source-faithful ingestion records
- `core`: normalized business entities and facts
- `ops`: operational tracking, sync state, run logs, control-plane metadata
- `dm`: data marts, read models, materialized views, analytical or page-oriented aggregations
- `app`: application data owned by the web product, such as users and preferences
- `web`: HTTP, authentication, authorization, page-facing APIs, application orchestration

### `raw`

`raw` stores source-facing data with minimal semantic reshaping.

Rules:

- preserve source fields whenever practical
- support reprocessing and traceability
- do not optimize `raw` for page consumption

### `core`

`core` stores normalized domain entities and business facts.

Rules:

- model stable business meaning, not temporary UI shape
- prefer explicit domain names over source-specific names when meaning improves
- do not store user-specific application state here
- do not add page-only denormalized convenience columns unless the value is truly core-domain data

### `ops`

`ops` stores control-plane and operational information.

Rules:

- sync logs, job states, backfill progress, and execution metadata belong here
- UI admin features should prefer `ops` as their source of truth
- scheduler-specific local files are not the long-term control plane

### `dm`

`dm` stores read models and analytical views.

Rules:

- use `dm` for expensive, reusable, page-oriented, or reporting-oriented queries
- keep `dm` derived from `core` and `ops`, not from ad hoc page logic
- when multiple pages need the same assembled data shape, prefer `dm` over repeated query duplication

### `app`

`app` stores application-owned product data.

Rules:

- users, roles, portfolios, preferences, saved filters, alerts, layout state, and similar product data belong here
- no market-data entities belong in `app`
- `app` must not become an unstructured catch-all schema

### `web`

`web` is the application delivery layer and BFF layer.

Rules:

- it provides authentication, authorization, API contracts, and page-facing orchestration
- it consumes `core`, `dm`, `ops`, and `app`
- it does not own ingestion logic
- it does not redefine foundational market-data semantics

## Web Architecture Principles

The web layer is designed as a long-term application platform, not a thin temporary adapter.

Recommended structure:

- `src/web/api`: routers and API entrypoints
- `src/web/schemas`: request and response models
- `src/web/services`: application orchestration and business workflow
- `src/web/queries`: read-model assembly for page-facing needs
- `src/web/repositories`: persistence for `app` data
- `src/web/auth`: token, password, and permission utilities
- `src/web/middleware`: request-scoped cross-cutting concerns

### Router Rules

Routers should:

- validate inputs
- resolve dependencies
- return consistent HTTP responses
- delegate business logic

Routers should not:

- contain complex SQL
- contain multi-step business workflows
- embed page-specific formatting logic beyond protocol serialization

### Service Rules

Services should:

- orchestrate application workflows
- coordinate repositories and queries
- enforce use-case-level rules

Services should not:

- become generic dumping grounds for unrelated helpers
- hide fundamental schema mistakes behind clever orchestration

### Query Rules

Query services should:

- build page-facing read models
- combine multiple foundation tables when needed
- shield the front end from schema complexity

Query services should not:

- mutate business state
- be used as a replacement for persistent derived models when a stable `dm` model is warranted

### Repository Rules

Repositories in the web layer should:

- persist `app` schema data
- provide explicit operations around application-owned entities

Repositories should not:

- duplicate the ingestion DAOs used by the data foundation
- casually become a second database abstraction framework across all schemas

## BFF Principles

`goldenshare` will use a BFF-style web layer.

In this project, BFF means:

- the front end talks to page-oriented APIs
- APIs return page models, not raw table rows
- the BFF assembles data from `core`, `dm`, `ops`, and `app`

This does not mean:

- every page gets custom unstructured backend logic
- routers directly evolve around one-off UI shortcuts
- the web layer becomes the new data foundation

The BFF layer must remain disciplined and layered.

## API Contract Principles

API contracts should be stable and product-oriented.

Rules:

- use versioned API prefixes such as `/api/v1`
- design response models around product needs, not table mirroring
- keep response shape stable even when internal storage changes
- use consistent error envelopes
- include request tracing metadata where appropriate

The front end must not depend on:

- database table names
- schema names
- internal ORM model names
- internal join logic

## Environment and Deployment Principles

The web platform must support both local development deployment and remote production deployment with the same codebase.

Rules:

- use one codebase for local and production environments
- distinguish environments through configuration, not through divergent codepaths
- prefer environment variables and environment files as the source of deployment configuration
- keep startup shape consistent across environments
- local and production must remain operationally isolated through separate configuration values

This means:

- local and production may use different database URLs
- local and production may use different secrets
- local and production may use different logging levels and debug flags
- local and production should still run the same application entrypoint

This does not allow:

- a separate local-only app implementation
- a separate production-only app implementation
- feature behavior that quietly forks by environment unless explicitly configured

Deployment convenience is a design goal.

Rules:

- the web app must have a clear standalone startup entrypoint
- health checks must exist for deployment verification
- environment configuration must be documented
- local development startup and production startup should be straightforward and repeatable

## Data Access Decision Rules

When building a new page or endpoint, choose the source layer by following this order:

1. If the query is simple and directly reflects stable domain data, read from `core`
2. If the query is operational or run-state oriented, read from `ops`
3. If the query is expensive, reused, heavily aggregated, or page-oriented, create or use `dm`
4. If the data is user-owned product state, store and read it from `app`

Do not create application-facing mirror tables simply to imitate another project.

## Feature Design Checklist

Every new feature should be reviewed with these questions:

1. Is this market data, application data, operational data, or a derived read model?
2. Which layer should own it: `core`, `app`, `ops`, or `dm`?
3. Does the front end need a page model that differs from storage models?
4. Should the read path be implemented as a query service now, or is it stable enough for `dm`?
5. Does this change preserve layer boundaries?
6. Am I introducing compatibility behavior only because of an old project shape?
7. If I am taking a shortcut, what is the convergence plan?

## Rules for External UI Migration

When reusing external UI ideas or assets:

- reuse page flow and interaction ideas if helpful
- adapt visual structure as needed
- rebuild API contracts around `goldenshare`
- rebuild backend implementation around `goldenshare`

Do not:

- mirror old table names into our schemas
- mirror old scheduler behavior into our operations model
- preserve old API shapes unless they are still the best long-term shape
- keep old abstractions just because they existed elsewhere

## Prohibited Shortcuts

The following should be treated as anti-patterns:

- complex SQL directly inside routers
- front-end code depending on storage field names
- adding user/product state into `core`
- changing foundational schemas to satisfy one page quickly
- creating duplicate mirror tables just to reduce adapter work
- coupling admin UI to local log-file parsing as the primary long-term design
- allowing one page's temporary needs to redefine system-wide naming

## Platform Verification Principles

The web platform must maintain a non-business platform verification page and a stable platform regression suite.

These are platform anti-corrosion assets, not optional demos.

Rules:

- maintain a platform verification page dedicated to validating platform capabilities
- keep this page focused on platform concerns such as health, authentication, current user resolution, permission checks, and error handling
- do not let this page drift into a business page
- maintain automated regression tests for platform capabilities
- treat platform verification as mandatory regression coverage for future web work

The platform verification layer must be included in regression validation when:

- adding new web features
- changing authentication or authorization
- changing middleware
- changing exception handling
- changing configuration loading
- changing application startup or deployment behavior
- changing foundational web routing structure

If platform verification breaks, fixing it takes priority over adding more business features on top.

## Exception Policy

Exceptions are allowed only when they are explicit and temporary.

A valid exception should record:

- what rule is being bent
- why the shortcut is needed now
- what risk it introduces
- what future convergence step is expected

Silent exceptions are not acceptable.

## First-Phase Web Platform Scope

The first web phase should focus only on platform foundations:

- web app skeleton
- configuration
- authentication
- authorization
- user model
- admin/user permission boundaries
- testing scaffold
- logging and request tracing
- developer documentation

The first phase should also include:

- environment-aware deployment configuration for local and production use
- a platform verification page
- platform regression tests that are intended to be kept for the long term

The first web phase should avoid business-domain functionality except what is strictly required to validate the platform foundation.

## Documentation and Review Rule

Before implementing meaningful new modules in the web application:

- consult this document
- state which principles guide the design
- call out any planned exceptions

Code review should evaluate not only correctness, but also adherence to these principles.

## Evolution Rule

This document should evolve with the system, but changes to it should be deliberate.

If the architecture changes, update this document before or with the implementation so future work stays aligned.
