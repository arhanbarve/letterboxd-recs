# Marquee — Letterboxd Recommender

Scrapes a Letterboxd profile, enriches with TMDB, and recommends unwatched films with a predicted ★ rating and match %. Supports multiple people sharing one deployment — each person's data is scoped to their own Letterboxd username.

## Local setup

**Backend:**
```bash
cd backend
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
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
- Open http://localhost:5173, enter your Letterboxd username, click "Refresh my data".

## Test

```bash
cd backend && .venv/bin/python -m pytest -v
```

## Deploying so friends can use it

Two pieces: backend on **Railway**, frontend on **Vercel**. Both have free tiers sufficient for a small friend group.

### Backend (Railway)

1. Create a Railway account and project, connect this repo, set the service root to `backend/`.
2. Railway auto-detects `backend/railway.json` (build installs deps + the Playwright Chromium browser; start runs uvicorn on Railway's assigned port).
3. Add a **persistent volume** to the service (Railway dashboard → your service → Settings → Volumes), mounted at a path like `/data`. Set the env var `DB_PATH=/data/letterboxd.db` so the SQLite file survives redeploys.
4. Set environment variables on the Railway service:
   - `TMDB_API_KEY` — your TMDB key
   - `DB_PATH` — `/data/letterboxd.db` (matching the volume mount)
   - `CORS_ORIGINS` — your Vercel frontend URL once you have it (comma-separate multiple origins if needed)
5. Deploy. Note the public Railway URL (e.g. `https://your-app.up.railway.app`).

### Frontend (Vercel)

1. Create a Vercel account, import this repo, set the project root to `frontend/`.
2. Vercel auto-detects Vite. Set the environment variable `VITE_API_BASE_URL` to your Railway backend URL from above.
3. Deploy. Share the resulting Vercel URL with friends — each person enters their own Letterboxd username in the app (saved to their browser), and everyone's data stays isolated on the shared backend.

### Notes

- Everyone shares one TMDB API key (fine at friend-group scale — TMDB's rate limit is generous).
- A refresh scrapes the real Letterboxd site via a headless browser (Letterboxd sits behind Cloudflare bot-protection that blocks plain HTTP scraping) — expect a refresh to take several minutes for a profile with many rated films.
- No accounts/auth: anyone with the URL can enter any Letterboxd username. Fine for a small trusted friend group; not intended for public/untrusted use.
