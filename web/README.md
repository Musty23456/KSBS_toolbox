# KSBS TOOLBOX — Web Admin Dashboard

React + TypeScript admin dashboard for KSBS TOOLBOX. Lets administrators and
supervisors build surveys, publish them for field collection, review
submissions, and manage enumerator/staff accounts. Talks to the
[backend API](../backend) over REST.

## Stack

- React 18 + TypeScript
- Vite (build tool / dev server)
- react-router-dom (routing)
- axios (API client)
- Plain CSS with a small design-token system (no UI framework) — see
  `src/styles/tokens.css` and `src/styles/global.css`

## Running locally

Requires Node.js 18+.

```bash
cd web
npm install
cp .env.example .env
# Edit .env if your backend isn't at http://localhost:8000
npm run dev
```

Open `http://localhost:5173`. Log in with one of the demo accounts created
by the backend's seed script (see `backend/README.md`).

## Building for production

```bash
npm run build
```

Outputs static files to `dist/`. This is a pure client-side SPA — it can be
hosted on any static host, but needs SPA fallback routing (all paths serve
`index.html`) since it uses client-side routing.

## Deployment

Config files are included for the two most common free static hosts:

- **Netlify**: `netlify.toml` is already set up — connect the repo, set
  `VITE_API_BASE_URL` in the Netlify UI's environment variables, deploy.
- **Vercel**: `vercel.json` is already set up — same idea, set the env var
  in the Vercel project settings.
- **GitHub Pages / Cloudflare Pages**: build with `npm run build` and
  publish the `dist/` folder; make sure your host serves `index.html` for
  unknown paths (SPA fallback), since GitHub Pages does not do this by
  default without an extra `404.html` trick.

**Important**: this is a static frontend only. It cannot host the backend
API — deploy `backend/` separately (e.g. Render, Railway, Fly.io, a VPS) and
point `VITE_API_BASE_URL` at it.

## Pages

- `/login` — sign in
- `/` — overview (survey and submission counts)
- `/surveys` — list, publish/unpublish, archive
- `/surveys/new`, `/surveys/:id` — form builder: add/reorder/remove
  questions, configure validation, skip logic (relevance expressions),
  calculated fields, and choices, per question
- `/submissions` — filterable submission list with an answer-level detail
  panel
- `/users` — manage enumerator/supervisor/administrator accounts
  (administrator and supervisor roles only)
- **Online enumerators** (`/online-enumerators`, Admin/Supervisor) — live
  presence board, auto-refreshes every 15 seconds.


## Design notes

The visual design is deliberately not a generic SaaS dashboard: it borrows
from paper field registries and ledgers (numbered questions, hairline
table rows, an ink sidebar against a sage-paper content area) since the
audience is running an official statistical field operation, not browsing
a consumer product. See `src/styles/tokens.css` for the full palette/type
system if you want to reskin it for a different organization's branding.

## Styling layers

- `src/styles/tokens.css` — colours, spacing, type scale.
- `src/styles/global.css` — the original base styles.
- `src/styles/polish.css` — the additive design and animation layer
  (imported last in `main.tsx`). Delete this file and its import to return
  to the original look.

## Known limitations / next steps

- Drag-and-drop question reordering was intentionally implemented as
  simple up/down buttons instead of a drag library, to keep the dependency
  surface small and behavior predictable — swap in a library like
  `@dnd-kit/core` if true drag-and-drop is wanted.
- The submissions page doesn't yet support CSV/Excel export from the UI —
  the backend has all the data needed (`GET /api/submissions`); adding an
  "Export" button that requests CSV would be a natural next step.
- No offline support in the web dashboard (by design — offline-first is
  the Android app's job; the web dashboard assumes office/desk connectivity).
