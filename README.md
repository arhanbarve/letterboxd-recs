# Letterboxd Recs by Arhan

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

**Backend:**
```bash
cd backend
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # fill in TMDB_API_KEY
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
cd backend && .venv/bin/python -m pytest -v     # unit + API
cd frontend && npm test                          # unit
cd frontend && npx playwright test               # E2E (needs the backend running)
```

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

Two pieces: backend on **Railway**, frontend on **Vercel**. Both have free tiers sufficient for a small friend group.

### Backend (Railway)

1. Create a Railway account and project, connect this repo, set the service root to `backend/`.
2. Railway auto-detects `backend/railway.json` (installs deps; starts uvicorn on Railway's assigned port).
3. Add a **persistent volume** to the service (Railway dashboard → your service → Settings → Volumes), mounted at a path like `/data`. Set the env var `DB_PATH=/data/letterboxd.db` so the SQLite file survives redeploys. **Without this, every redeploy wipes your import** and you have to upload the zip again.
4. Set environment variables on the Railway service:
   - `TMDB_API_KEY` — your TMDB key
   - `OMDB_API_KEY` — optional, adds IMDb/Rotten Tomatoes scores to the top results
   - `DB_PATH` — `/data/letterboxd.db` (matching the volume mount)
   - `CORS_ORIGINS` — your Vercel frontend URL once you have it (comma-separate multiple origins if needed)
   - `CORS_ORIGIN_REGEX` — optional pattern so Vercel preview deployments (a new hostname per push) aren't rejected by CORS. **Anchor it** with `^` and `$`, e.g. `^https://your-project(-[a-z0-9]+-[a-z0-9-]+)?\.vercel\.app$` — an unanchored `.*\.vercel\.app` lets any site hosted on Vercel call your API
5. Deploy. Note the public Railway URL (e.g. `https://your-app.up.railway.app`).

### Frontend (Vercel)

1. Create a Vercel account, import this repo, set the project root to `frontend/`.
2. Vercel auto-detects Vite. Set the environment variable `VITE_API_BASE_URL` to your Railway backend URL from above.
3. Deploy. Share the resulting Vercel URL with friends — each person uploads their own export, and everyone's data stays isolated on the shared backend.

If the deployed app reports "Failed to fetch", it is almost always one of those two settings: `VITE_API_BASE_URL` missing on Vercel (the frontend then calls `127.0.0.1`), or the Vercel origin missing from `CORS_ORIGINS` on Railway.

### Notes

- Everyone shares one TMDB API key (fine at friend-group scale — TMDB's rate limit is generous).
- TMDB ids are resolved from title+year, since the export identifies films only by a `boxd.it` shortlink. Resolution is cached per film, so the first refresh after an import is the slow one. Any film TMDB can't match is skipped and counted in the finish message.
- Letterboxd records a film's premiere year while TMDB records its release year, so lookups retry ±1 year — without that, a couple of percent of films fail to match for no real reason.
- Candidate generation is capped (50 seed films, 5000 candidates) to keep a refresh in the minutes, not hours.
- No accounts, no passwords, no email. Access is one per-username code, minted at first import (see above) — enough to keep one person's ratings from another's on a shared deployment, but it is not a hardened identity system: anyone holding a code has full access to that username's data.
- Rate limits are per client IP and in-process, so they reset on redeploy and are shared by everyone behind one NAT. Tune with `RATE_LIMIT_IMPORTS_PER_HOUR` / `RATE_LIMIT_REFRESHES_PER_HOUR`.
- Uploads are capped at 25MB compressed and 200MB uncompressed, so a zip bomb is rejected from its header rather than unpacked.
