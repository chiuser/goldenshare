# Web Platform Phase 1

> 历史文档（归档）：本文件包含虚拟拆仓前后的阶段性描述。当前以 [current-architecture-baseline.md](/Users/congming/github/goldenshare/docs/architecture/current-architecture-baseline.md) 为准。

## Goal

Phase 1 builds the web platform foundation for `goldenshare`.

This phase does not migrate business pages and does not implement business-domain APIs.

The goal is to create a clean, extensible, production-usable web platform skeleton that future business modules can safely build upon.

## Scope

Phase 1 includes:

- web application skeleton
- environment-aware configuration
- local and remote deployment model
- authentication foundation
- authorization foundation
- application user model
- platform-level API infrastructure
- platform verification page
- platform regression tests
- developer and deployment documentation

Phase 1 does not include:

- market data APIs
- portfolio APIs
- chart APIs
- sentiment APIs
- admin business functionality
- migration of old external pages
- compatibility with external repository backend structures

## Design Constraints

Phase 1 follows [design-principles.md](/Users/congming/github/goldenshare/docs/architecture/design-principles.md).

Key constraints:

- one codebase for local and production deployment
- configuration drives environment behavior
- no business features except what is strictly required to validate the platform
- external repositories are only UI references, not architecture references
- platform verification assets must be treated as long-term anti-corrosion infrastructure

## Target Directory Structure

Recommended phase-1 web structure:

```text
src/models/
  app/
    app_user.py

src/web/
  app.py
  lifespan.py
  run.py
  settings.py
  dependencies.py
  exceptions.py
  logging.py

  api/
    router.py
    v1/
      router.py
      auth.py
      users.py
      admin.py
      health.py

  auth/
    jwt_service.py
    password_service.py
    dependencies.py

  schemas/
    common.py
    auth.py
    user.py

  services/
    auth_service.py
    user_service.py

  repositories/
    user_repository.py

  domain/
    user.py
    auth.py

  middleware/
    request_id.py
    access_log.py

  static/
    platform-check.html
    platform-check.js

.env.web.example
scripts/goldenshare-web.service
```

## Responsibilities by Layer

### `src/web/api`

Responsibilities:

- HTTP route declarations
- request validation
- dependency resolution
- response protocol handling

Non-goals:

- business orchestration
- direct complex SQL
- environment branching

### `src/web/auth`

Responsibilities:

- password hashing and verification
- JWT encode and decode
- auth dependencies
- permission dependencies

### `src/web/services`

Responsibilities:

- authentication workflow
- user self-profile workflow
- permission-related orchestration

### `src/web/repositories`

Responsibilities:

- persistence for `app` schema user entities

### `src/web/schemas`

Responsibilities:

- request and response contracts
- error envelope contract

### `src/web/middleware`

Responsibilities:

- request ID propagation
- access logging

## Database Design

Phase 1 only introduces application-layer user data.

### Schema

- `app`

### Table: `app.app_user`

Recommended fields:

- `id` integer primary key
- `username` varchar not null unique
- `password_hash` varchar not null
- `display_name` varchar null
- `email` varchar null
- `is_admin` boolean not null default false
- `is_active` boolean not null default true
- `last_login_at` timestamptz null
- `created_at` timestamptz not null
- `updated_at` timestamptz not null

Recommended indexes:

- unique index on `username`
- optional index on `is_active`

Phase 1 explicitly excludes:

- `user_portfolio`
- `role`
- `permission`
- `user_preference`
- any business-facing user state

## Authentication and Authorization

Phase 1 uses a minimal but production-usable model.

### Authentication

- JWT bearer token
- password hashing through a mature library
- current user resolved by token and validated against database state

### Authorization

Phase 1 supports only:

- authenticated user
- admin user
- active user validation

This is intentionally minimal. Full RBAC is deferred.

## API Surface

Phase 1 only exposes platform APIs.

### Health

- `GET /api/health`
- `GET /api/v1/health`

### Authentication

- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`
- `POST /api/v1/auth/logout`

### User self

- `GET /api/v1/users/me`

### Admin capability validation

- `GET /api/v1/admin/ping`

Purpose of `admin/ping`:

- validate admin dependency chain
- validate permission enforcement
- provide a stable non-business admin regression endpoint

## Error and Response Model

Phase 1 should standardize error responses.

Recommended error envelope:

```json
{
  "code": "unauthorized",
  "message": "Authentication required",
  "request_id": "..."
}
```

Target error classes to normalize:

- validation errors
- unauthorized
- forbidden
- not found
- conflict
- internal server errors

## Environment and Deployment Model

Phase 1 must support:

- local development deployment
- remote production deployment

with the same codebase and same application entrypoint.

### Core Rule

Environment behavior is configuration-driven.

The application code must not fork into separate local and production implementations.

### Recommended settings

- `APP_ENV`
- `DATABASE_URL`
- `WEB_HOST`
- `WEB_PORT`
- `WEB_DEBUG`
- `WEB_CORS_ORIGINS`
- `WEB_LOG_LEVEL`
- `JWT_SECRET`
- `JWT_EXPIRE_MINUTES`

### Recommended environment files

- local: `.env.web.local`
- production: `/etc/goldenshare/web.env`

Here, `local` describes the deployment/runtime context, not necessarily a local database.
Running the web app locally against a remote database is a valid and supported setup.

### Startup examples

Local:

```bash
export GOLDENSHARE_ENV_FILE=.env.web.local
uvicorn src.platform.web.app:app --reload
```

Production:

```bash
export GOLDENSHARE_ENV_FILE=/etc/goldenshare/web.env
uvicorn src.platform.web.app:app --host 0.0.0.0 --port 8000
```

### Deployment Requirements

Phase 1 should also provide:

- clear startup documentation
- health-check endpoint
- example production service configuration, such as a systemd unit sample

## Platform Verification Page

Phase 1 includes a dedicated non-business verification page.

### Purpose

This page validates platform capabilities, not business features.

### Recommended route

- `/platform-check`

### Page capabilities

- verify static asset serving
- call `GET /api/health`
- submit login request
- display current user profile
- call `GET /api/v1/admin/ping`
- show request IDs and error messages

### Rules

- no business-domain content
- not part of the future business navigation
- must remain small, stable, and easy to use for manual smoke verification

## Platform Regression Tests

Phase 1 platform tests are mandatory long-term regression assets.

### Required API tests

- health endpoint works
- login succeeds with valid credentials
- login fails with invalid credentials
- `auth/me` requires valid token
- `auth/me` returns current user
- `admin/ping` returns 403 for non-admin
- `admin/ping` returns 200 for admin
- error envelope shape is stable
- request ID is present

### Required repository and service tests

- create user
- query user by username
- verify password hashing
- verify JWT encode and decode
- inactive user rejection
- last login update

### Verification-page tests

At minimum:

- page route is reachable
- referenced static assets load correctly

If browser automation is added later, this page should be the first stable E2E smoke target.

### Regression Policy

These tests must be included in regression verification for:

- any web platform change
- any new business module built on the platform
- any auth change
- any middleware change
- any deployment or startup change

## Middleware and Observability

Phase 1 should include:

- request ID middleware
- access log middleware
- structured enough request logging for debugging deployment and auth issues

Recommended access log fields:

- request ID
- method
- path
- status code
- duration
- user ID when available

## Initialization and Operations

Phase 1 should provide a user creation path for platform verification.

Recommended option:

- `python -m src.scripts.create_user --username ... --password ... --admin`

This allows:

- creating a local admin user
- verifying login flow quickly
- verifying admin permission endpoints

## Documentation Deliverables

Phase 1 should produce or update:

- [design-principles.md](/Users/congming/github/goldenshare/docs/architecture/design-principles.md)
- this phase-1 design document
- web startup instructions
- environment variable documentation
- local deployment instructions
- production deployment instructions
- platform regression checklist

## Recommended Implementation Order

1. Create web skeleton and router structure
2. Add web settings and startup entrypoint
3. Add middleware and exception handling
4. Add `app.app_user` migration and model
5. Implement repository, auth services, and auth dependencies
6. Implement health, login, me, and admin ping APIs
7. Add create-user script
8. Add platform verification page
9. Add automated tests
10. Finalize docs

## Review Checklist

Phase 1 is ready for implementation when we agree on:

- directory structure
- `app.app_user` schema
- auth model
- API list
- environment strategy
- deployment model
- platform verification page scope
- regression expectations
