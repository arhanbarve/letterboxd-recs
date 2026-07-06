# Letterboxd Personal Recommender — Design

**Date:** 2026-07-06
**Status:** Approved for planning

## Purpose

Letterboxd has no native recommendation engine. This is a single-user, local tool that scrapes one Letterboxd profile's ratings, enriches them with TMDB metadata, builds a taste profile, and recommends unwatched films — each with a predicted star rating, a match percentage, and a human-readable reason. A React UI displays the ranked recommendations and a view of the derived taste profile.

Scope is deliberately single-user: no collaborative filtering, no scraping of other profiles, no accounts.

## Success Criteria

- Given a public Letterboxd username, the tool scrapes all rated films and matches each to a TMDB record.
- It produces a ranked list of unwatched recommendations, each with predicted ★, match %, and a "why" explanation.
- A React UI shows the recommendations and a taste-profile view, with a single "Refresh" button that re-runs the whole pipeline.
- Core scoring logic is unit-tested against a small hand-built dataset with known expected output.

## Architecture

Local app. Python + FastAPI backend, React frontend, SQLite storage.

```
Letterboxd profile pages (scrape)
        │  title, year, your rating, TMDB id (from film page)
        ▼
   TMDB API enrichment ──────────────► SQLite (films, genres, keywords, cast, ratings)
        │  genres, director, cast, keywords, decade, poster, vote avg
        ▼
   Taste Profile Builder  ─────────────► affinity dicts (genre/director/actor/keyword/decade)
        │
        ▼
   Candidate Generator (TMDB /recommendations + /similar for your ≥4★ films, deduped, minus watched)
        │
        ▼
   Scorer  ── match % (weighted affinity) + predicted ★ (k-NN) + why-tags
        │
        ▼
   FastAPI  ──►  React UI (recommendations page + taste-profile page + Refresh button)
```

A single "Refresh" action re-runs the entire pipeline.

## Components

### 1. Scraper (Letterboxd)

- Input: a public Letterboxd username (from config).
- Scrapes the paginated `/{username}/films/` listing to enumerate every logged film with the user's star rating.
- For each film, fetches the Letterboxd film page and extracts the **embedded TMDB id** (Letterboxd links each film to themoviedb.org / exposes `data-tmdb-id`). This avoids fuzzy title/year matching and its failure class (remakes, foreign titles, same-title collisions).
- Per film captured: title, year, Letterboxd slug, TMDB id, your rating, watched date if present.
- Politeness: fixed delay between requests, single profile only, no auth (public profile assumed).
- Films watched but **unrated** are captured for exclusion purposes but contribute no affinity signal (no star).
- Requires the profile to be public. If a film page yields no TMDB id, log and skip it (rare).

**Tested via:** saved sample Letterboxd HTML fixtures (listing page + film page) → assert parsed fields.

### 2. TMDB Enricher

- For each TMDB id, fetch details: genres, director (from crew), top-5 cast, keywords, poster path, TMDB vote average. Derive decade from year.
- Cache every TMDB response in SQLite. Refresh re-hits TMDB only for films not already cached.
- Config holds the TMDB API key.

### 3. Storage (SQLite)

Single local `.db` file.

- `films`: `tmdb_id` (PK), title, year, decade, director, poster_path, tmdb_vote_avg
- `film_genres`: (film_id, genre)
- `film_keywords`: (film_id, keyword)
- `film_cast`: (film_id, actor)
- `ratings`: (film_id, your_rating, watched_date) — rows only for films you rated
- `watched`: (film_id) — every film you logged, rated or not (drives exclusion)
- `recommendations`: (film_id, match_pct, predicted_rating, why_tags, computed_at) — cache of the last run

### 4. Taste Profile Builder

Five affinity dictionaries, one per feature type: genre, director, actor, keyword, decade.

- For each feature value appearing across your rated films:
  `affinity(value) = Σ (your_rating − 2.5)` over films containing that value.
  (2.5 = neutral midpoint on the 0.5–5★ scale. Positive = you like it, negative = you avoid it.)
- Normalize each dict (e.g. divide by max abs value) so feature types are comparable.

### 5. Candidate Generator (hybrid step)

- Take your films rated ≥ 4★. For each, call TMDB `/movie/{id}/recommendations` and `/movie/{id}/similar`.
- Pool and dedupe results; drop anything already in `watched`.
- This bounds the candidate set to plausibly-relevant films instead of all of TMDB.
- Fallback: if you have very few ≥4★ films (small pool), lower the threshold to ≥3.5★ to ensure a usable candidate set.

### 6. Scorer

For each candidate, fetch/enrich its TMDB metadata (same enricher), then compute:

- **Match %** — weighted sum of the candidate's feature affinities, using weights:
  genre 25%, keyword 25%, director 20%, actor 20%, decade 10%.
  Min-max normalized to 0–100% **across the current candidate pool** (so match % is relative to this run's pool, not an absolute scale).
- **Predicted ★** — k-NN over your rated films. Build a feature vector (genre + keyword one-hot) for the candidate and for each rated film; find the k≈10 most cosine-similar rated films; predicted rating = similarity-weighted average of their star ratings.
- **Why tags** — the top 2–3 feature values contributing most to the match score, rendered as text (e.g. "Because you love Bong Joon-ho, dark comedy, 2010s thrillers").

Output ranked by match % (predicted ★ shown alongside). Excludes anything already watched.

**Tested via:** small hand-built dataset (a handful of rated films + candidates) with known expected affinity values, predicted ratings, and ordering.

### 7. API (FastAPI)

- `POST /api/refresh` — runs scrape → enrich → build profile → generate candidates → score → cache. Returns progress/status.
- `GET /api/recommendations` — ranked list: poster, title, year, predicted ★, match %, why-tags.
- `GET /api/taste-profile` — top genres/directors/actors/decades by affinity, for the profile view.

### 8. Frontend (React)

- **Recommendations page** — ranked cards (poster, title/year, predicted ★, match %, why-tags). "Refresh my data" button with loading state that calls `POST /api/refresh` then reloads results.
- **Taste Profile page** — top genres, directors, actors, decades by affinity, shown as bar-chart-style lists.

## Configuration

- Letterboxd username
- TMDB API key
- Stored in a `.env` / config file, not committed.

## Testing Strategy

- **Scraper:** unit tests parse saved Letterboxd HTML fixtures (listing + film page); assert extracted fields including TMDB id.
- **TMDB matching/enrichment:** tests over recorded/mocked TMDB responses; verify caching skips re-fetch.
- **Scoring:** unit tests for affinity calculation, match %, and k-NN predicted rating against a small dataset with hand-computed expected output.

## Explicit Non-Goals (YAGNI)

- No collaborative filtering / multi-profile scraping.
- No reviews/diary/watchlist/lists scraping (ratings + watched only).
- No accounts, auth, or cloud deploy.
- No scheduled/background refresh (manual button only).
- No frontend filtering/sorting in v1 (ranked list + profile view only).
