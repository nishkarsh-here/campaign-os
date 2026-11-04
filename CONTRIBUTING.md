# Contributing to Campaign OS

Thanks for considering a contribution. Small, focused changes are easiest to
review and help keep the product's documented contracts accurate.

## Before opening a change

1. Search existing issues and pull requests for related work.
2. For a substantial feature or a change to a public API, open an issue first
   so the scope and user impact can be discussed.
3. Do not include credentials, customer data, private documents, or material
   that you do not have permission to share. Use fictional data in examples.

## Local setup

Follow the [README quick start](README.md#quick-start) and the more detailed
[testing guide](docs/TESTING.md). The backend suite uses PostgreSQL 16 or newer
with `pgcrypto`, `citext`, and `vector` (pgvector). Provider-backed tests are
excluded from the ordinary test run; do not add a test that spends money or
requires a real API key to pass.

## Change expectations

- Preserve the domain contracts and architecture boundaries documented in
  [the architecture guide](docs/ARCHITECTURE.md).
- Add or update tests for behavior changes and bug fixes.
- Update API, schema, deployment, and workflow documentation when behavior
  changes.
- Keep provider credentials on the server. Never add real secrets to source,
  examples, tests, logs, or screenshots.
- Keep changes focused and explain important trade-offs in the pull request.

## Checks before requesting review

From `backend/`:

```bash
uv run pytest
uv run ruff check app tests
uv run mypy app
```

From `frontend/`:

```bash
npm test
npm run lint
npm run typecheck
API_BASE_URL=https://api.example.com npm run build
```

The backend integration tests need a migrated test database. See
[`docs/TESTING.md`](docs/TESTING.md) for test layers and the live-provider test
boundary. Do not run live-provider tests in routine checks; they can incur
charges.

## Pull requests

Use the pull request template. Include the reason for the change, how it was
verified, and any migration, security, or deployment impact. Mark checks that
you could not run and explain why.
