---
title: "fix: Restrict /api/quotes/latest to approved quotes and isolate test suite from local.db"
type: fix
status: completed
date: 2026-03-30
---

# Fix: CodeX Review Findings from Commit 647296e

## Overview

Two bugs identified by cross-model CodeX review: a public endpoint exposing unapproved content, and a test fixture that mutates the developer's real SQLite database during startup.

## Problem Frame

Commit 647296e fixed route shadowing by moving `/api/quotes/latest` before `/{quote_id}`. This correctly made the endpoint reachable again, but exposed two latent issues:
1. The endpoint returns quotes of any moderation status to unauthenticated callers
2. The new test suite's `TestClient` triggers the app lifespan, which boots `LocalQuoteStore` against the real `local.db` before dependency overrides take effect

## Requirements Trace

- R1. Public API endpoints must only return APPROVED quotes to unauthenticated callers
- R2. Test suite must be fully hermetic — no reads or writes to developer's real `local.db`

## Scope Boundaries

- Do not change admin API behavior (admin endpoints already have auth gates)
- Do not refactor the lifespan function beyond what's needed for test isolation

## Key Technical Decisions

- **Default `status` to "APPROVED" in `api_latest_quote`**: Matches the pattern used by `api_get_quote` (line 517) which checks `quote.status != "APPROVED"`. Changing the Query default is the minimal fix — no new filtering logic needed.
- **Monkeypatch `LOCAL_DB_PATH` to `tmp_path` before `TestClient` enters**: The lifespan reads `LOCAL_DB_PATH` via `get_settings()`. Monkeypatching the env var and clearing the `lru_cache` before entering the `TestClient` context ensures the lifespan creates its `LocalQuoteStore` against a temp file. This is less invasive than bypassing lifespan entirely.

## Implementation Units

- [x] **Unit 1: Default /api/quotes/latest to APPROVED**

  **Goal:** Prevent unapproved quotes from being returned by the public latest endpoint.

  **Requirements:** R1

  **Dependencies:** None

  **Files:**
  - Modify: `app/main.py`
  - Modify: `tests/test_api.py`

  **Approach:**
  - Change `Query(default=None, ...)` to `Query(default="APPROVED", ...)` in `api_latest_quote`
  - Update `test_returns_latest` to assert the returned quote has `status == "APPROVED"`
  - Add a test that explicitly passes `?status=PENDING` and verifies it still works (this is intentional behavior — callers who explicitly request a status should get it)

  **Patterns to follow:**
  - `api_list_quotes` uses `Query(default="APPROVED", alias="status")` — same pattern

  **Test scenarios:**
  - Happy path: `GET /api/quotes/latest` returns a quote with `status == "APPROVED"`
  - Happy path: `GET /api/quotes/latest?status=APPROVED` returns an approved quote
  - Edge case: `GET /api/quotes/latest` when only PENDING/REJECTED quotes exist returns null/empty
  - Explicit filter: `GET /api/quotes/latest?status=PENDING` still returns pending quotes (not blocked)

  **Verification:**
  - `pytest tests/test_api.py::TestApiLatestQuote` passes
  - Default call no longer leaks unapproved content

- [x] **Unit 2: Isolate test fixtures from real local.db**

  **Goal:** Ensure the app lifespan creates its `LocalQuoteStore` against a temporary database, not the developer's real `local.db`.

  **Requirements:** R2

  **Dependencies:** None (independent of Unit 1)

  **Files:**
  - Modify: `tests/conftest.py`

  **Approach:**
  - In the `client` fixture, monkeypatch `LOCAL_DB_PATH` to point at `tmp_path / "lifespan.db"` **before** entering `TestClient`
  - The existing `monkeypatch.setenv("LOCAL_MODE", "true")` and `get_settings.cache_clear()` already run before `TestClient` — add `LOCAL_DB_PATH` to the same block
  - This ensures `lifespan()` → `get_settings()` → `Settings(**os.environ)` picks up the temp path

  **Patterns to follow:**
  - The fixture already monkeypatches `LOCAL_MODE`, `ADMIN_CREDENTIALS`, `ADMIN_EMAILS`, `ADMIN_PASSWORD` — add `LOCAL_DB_PATH` in the same block

  **Test scenarios:**
  - Happy path: Running the full test suite does not create or modify `local.db` in the project root
  - Integration: The `client` fixture still works — seeded data is accessible through the test client

  **Verification:**
  - `pytest` passes with no `local.db` created in project root
  - Existing tests continue to pass without modification

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Changing default status could break callers relying on `?status=` being unfiltered by default | The endpoint is internal/undocumented; the change aligns with all other public endpoints |
| Monkeypatching LOCAL_DB_PATH might not take effect if Settings is cached | The fixture already calls `get_settings.cache_clear()` before TestClient — just ensure LOCAL_DB_PATH env is set before that clear |

## Sources & References

- CodeX review output (gpt-5.4) of commit 647296e
- `app/main.py:499-508` — the affected endpoint
- `app/main.py:74-97` — lifespan function showing LOCAL_DB_PATH usage
- `tests/conftest.py:61-100` — the client fixture
