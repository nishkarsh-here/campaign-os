# frontend

Not scaffolded yet — this lands in **Milestone 1**. Scaffolding it now would add
~400 MB of `node_modules` and a pile of boilerplate before there is an API to
talk to.

Decisions already fixed (see `docs/UI_SPEC.md` and ADR-001/ADR-010):

- Next.js App Router · TypeScript · Tailwind · shadcn/ui
- npm (pnpm is not installed on this machine)
- Types are **generated** from the backend's OpenAPI schema into
  `src/lib/api-types.ts` via `openapi-typescript`. Hand-written duplicates of
  API types are a bug.
- The browser talks only to our FastAPI backend. No provider key, no Supabase
  service key, and no storage bucket is ever addressed from the client.

Scaffold command for Milestone 1:

```bash
npx create-next-app@latest frontend --typescript --tailwind --app --eslint --src-dir
```
