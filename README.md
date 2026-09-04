# Letterboxd Recs by Arhan

**Live:** [arhan-lbxd-recs.vercel.app](https://arhan-lbxd-recs.vercel.app) — frontend on Vercel,
API on Render, Postgres on Neon. The API sleeps when idle, so the first request
after a quiet spell takes a few seconds to wake.

You upload your own Letterboxd data export; the app enriches it with TMDB and recommends unwatched films with a predicted ★ rating and match %. Supports multiple people sharing one deployment — each person's data is scoped to their own Letterboxd username.

Nothing here crawls Letterboxd. Letterboxd sits behind Cloudflare bot-management that refuses automated crawling outright, so the data comes from the export Letterboxd gives you on request — which is also complete, instant, and impossible to get blocked.

## Getting your data in

1. Open [Letterboxd → Settings → Data](https://letterboxd.com/settings/data/) and click **Export Your Data**.
2. Drop the downloaded `letterboxd-<you>-<date>-utc.zip` onto the app's import panel.
3. Click **Generate recommendations**.

The app reads only `ratings.csv` (your ratings), `watched.csv` (so watched films are never recommended back to you), and `profile.csv` (your username — which is why you never have to type it correctly). Everything else in the zip is ignored, including your email address.

Re-import whenever you want new ratings counted. Scoring can be re-run any time without re-uploading.

### Your access code

A Letterboxd username is just a string anyone could type, so the first import under a username **claims** it: the app mints an access code, shows it once, and stores it in that browser. Every later read or write for that username has to present it back.

- You never need the code on the device you imported from — it is already saved there.
- Save it if you want to open your recommendations on another device; paste it when the app asks.
- Lose it and nobody, including you, can read or overwrite that username's data. Import under a slightly different username to start fresh.

Only the SHA-256 of a code is stored, so the database never holds a working code.

## Local setup

**Backend:** needs Postgres running locally.
```bash
brew services start postgresql@16     # or any Postgres you already run
createdb letterboxd_dev

cd backend
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # fill in TMDB_API_KEY; DATABASE_URL is preset for the db above
```
Get a free TMDB v3 API key at https://www.themoviedb.org/settings/api (create an account, then Settings → API → request a key).

**Frontend:**
```bash
cd frontend && npm install
```

## Run locally

- Backend: `cd backend && .venv/bin/uvicorn app.api:app --reload`
- Frontend: `cd frontend && npm run dev`
- Open http://localhost:5173 and follow the import panel.

## Test

```bash
cd backend && .venv/bin/python -m pytest -v     # unit + API (needs Postgres running)
cd frontend && npm test                          # unit
cd frontend && npx playwright test               # E2E (needs the backend running)
```

The Python tests run against a real throwaway Postgres database (`letterboxd_test`),
created and dropped by `tests/conftest.py` and emptied between tests. There is no
in-memory stand-in, because one would not prove the actual SQL works. Point the
suite at a different server with `TEST_ADMIN_DSN` / `TEST_DATABASE_URL`.

The E2E import tests use synthetic export fixtures and claim a fresh username on
each run. Regenerate the fixtures with
`cd backend && .venv/bin/python scripts/make_sample_export.py`.

`tests/e2e/app.spec.js` reads seeded data instead, so it needs a locally
imported account and its access code, and skips without them:

```bash
E2E_USERNAME=<user> E2E_ACCESS_CODE=<code> npx playwright test
```

Running the import suite repeatedly can hit the import rate limit; start the
backend with `RATE_LIMIT_IMPORTS_PER_HOUR=1000` while iterating.

## Deploying so friends can use it

Three pieces, all on free tiers that need no credit card: **Neon** for Postgres,
**Render** for the API, **Vercel** for the frontend.

The data lives in Postgres rather than on a disk, which is what makes a free
deployment possible at all — hosts give away compute far more readily than they
give away persistent storage.

### Database (Neon)

1. Create a project at [neon.tech](https://neon.tech). No card required.
2. Copy the **pooled** connection string (the one with `-pooler` in the host).
   Render's free instances sleep and reconnect constantly, which is what the
   pooled endpoint exists for.

The app creates its own tables on first start, so there is no migration step.

### Backend (Render)

`render.yaml` is committed, so this is a blueprint deploy:

1. At [render.com](https://render.com), New → Blueprint, point it at this repo.
2. It reads `render.yaml` — free plan, root `backend/`, uvicorn start command.
3. Set the three secrets in the dashboard (they are marked `sync: false`, so they
   are never read from the repo):
   - `DATABASE_URL` — the Neon pooled string
   - `TMDB_API_KEY`
   - `OMDB_API_KEY` — optional, adds IMDb/Rotten Tomatoes scores
4. Edit `CORS_ORIGINS` in `render.yaml` to your own Vercel URL, and the anchored
   `CORS_ORIGIN_REGEX` alongside it. **Keep it anchored** with `^` and `$` — an
   unanchored `.*\.vercel\.app` lets any site hosted on Vercel call your API.

Free Render instances sleep after ~15 minutes idle, so the first request after a
quiet spell takes a few seconds to wake. Nothing is lost when it sleeps, because
no state lives on the instance.

### Frontend (Vercel)

1. Create a Vercel account, import this repo, set the project root to `frontend/`.
2. Vercel auto-detects Vite. Set `VITE_API_BASE_URL` to your Render backend URL
   (e.g. `https://letterboxd-recs-api.onrender.com`).
3. Deploy. Share the resulting Vercel URL — each person uploads their own export,
   and everyone's data stays scoped to their own Letterboxd username.

If the deployed app reports "Failed to fetch", it is almost always one of those two settings: `VITE_API_BASE_URL` missing on Vercel (the frontend then calls `127.0.0.1`), or the Vercel origin missing from `CORS_ORIGINS` on the backend.

### Notes

- Everyone shares one TMDB API key (fine at friend-group scale — TMDB's rate limit is generous).
- TMDB ids are resolved from title+year, since the export identifies films only by a `boxd.it` shortlink. Resolution is cached per film, so the first refresh after an import is the slow one. Any film TMDB can't match is skipped and counted in the finish message.
- Letterboxd records a film's premiere year while TMDB records its release year, so lookups retry ±1 year — without that, a couple of percent of films fail to match for no real reason.
- Candidate generation is capped (50 seed films, 5000 candidates) to keep a refresh in the minutes, not hours.
- No accounts, no passwords, no email. Access is one per-username code, minted at first import (see above) — enough to keep one person's ratings from another's on a shared deployment, but it is not a hardened identity system: anyone holding a code has full access to that username's data.
- Rate limits are per client IP and in-process, so they reset on redeploy and are shared by everyone behind one NAT. Tune with `RATE_LIMIT_IMPORTS_PER_HOUR` / `RATE_LIMIT_REFRESHES_PER_HOUR`.
- Uploads are capped at 25MB compressed and 200MB uncompressed, so a zip bomb is rejected from its header rather than unpacked.
