# Recommendations Overhaul — Design Spec

Date: 2026-07-07
Status: Approved for planning
Account used for verification: `moviefan`

## Problem

The live app has several failures:

1. **Watched films are recommended back to the user.** Films the user has already rated on Letterboxd (e.g. *Silence of the Lambs*, *The Godfather Part II*, *Taxi Driver*) appear in recommendations.
2. **Recommendation reasons are generic and identical.** Every film shows "Because you like Drama, based on novel…" — the user's globally dominant features, not anything specific to the film.
3. **The Top Pick presentation is underwhelming** — small, not cinematic.
4. **Clicking a film only shows watch providers** — no synopsis or film detail.
5. **The Taste Profile page shows only genre + actor counts** — described by the user as "completely useless."
6. **The recommendations list is unbounded** (hundreds of films), with no cap and no meaningful cutoff.
7. **Match % is relative**, so any percentage-based cutoff is meaningless.

## Goals

Fix the correctness bug, make reasons specific and per-film, and redesign the two main surfaces (recommendations, taste profile) to feel cinematic and useful. No LLM in the recommendation path — reasons stay deterministic and free.

## Non-goals

- No change to the core scoring model weights (genre/keyword/director/actor/decade) beyond how the final percentage is normalized.
- No new external services or API keys beyond the existing TMDB key.
- No auth/accounts work.

---

## Workstream 1 — Fix watched-film leak (correctness)

### Root cause
`scrape_profile` walks `/{user}/films/` page by page. `default_get` (scraper.py:67) returns `page.content()` **even after exhausting retries on a 403/429** (line 77). When Cloudflare serves a challenge mid-crawl, the challenge HTML has no `a.next`, so `parse_next_page_url` returns `None` and pagination stops early. Films on unreached pages never enter the `watched` set (pipeline.py:86), and the candidate pool is `pool - watched_ids` (candidates.py:7), so those films become eligible recommendations.

Secondary leak: films whose TMDB-id parse fails are dropped entirely (scraper.py:89), so they can never be excluded.

### Changes
- **`default_get`**: after exhausting backoffs on a 403/429 (or on a detected challenge page), **raise** an exception instead of returning challenge HTML. The refresh surfaces this as a real error (the API already maps exceptions to an `error` stage).
- **Completeness assertion**: parse the profile's stated total film count from the films page (Letterboxd renders it in the header/stats). After the crawl, if `len(scraped)` is materially below the stated total, raise — never persist a partial scrape as if complete.
- **Record all watched films**: keep films even when `tmdb_id` is `None`. The `watched` set excludes by `tmdb_id` when present; additionally store the slug so a film with no TMDB link is still recorded as watched (defensive — such films rarely appear as TMDB candidates, but this closes the gap).

### Verification
Run a live refresh against `moviefan`. Confirm the three named films land in `watched` and do **not** appear in recommendations. Confirm scraped count matches the profile's stated total.

---

## Workstream 2 — Specific, per-film reasons ("name your films")

### Approach
`predict_rating` (scorer.py:39) already computes cosine similarity between each candidate and every rated film, keeping the top-k nearest **rated** neighbors. Those neighbors are the specific, per-film reason.

### Changes
- New `why` structure per recommendation (replaces `why_tags`):
  ```json
  {
    "neighbors": [
      {"title": "Zodiac", "rating": 5.0},
      {"title": "Se7en", "rating": 5.0}
    ],
    "connection": "same slow-burn dread"
  }
  ```
- **Neighbors**: top 2 cosine-nearest rated films with the highest `rating` among the near set (prefer films the user rated highly, so the reason cites loved films, not merely similar ones).
- **Connection**: derived from the strongest shared feature between the candidate and its neighbors — shared director → "directed by X"; else shared top actor → "starring X"; else the highest-weight shared keyword/genre cluster → a short human phrase. Deterministic mapping from feature type to phrase; no LLM.
- Render (card + hero + modal): *"Because you loved **Zodiac** (5★) and **Se7en** (5★) — {connection}."*
- If a candidate has no meaningful rated neighbor (cold case), fall back to a single specific tag (top shared feature), never the generic global-feature list.

### Storage
`recommendations.why_tags` (TEXT JSON) is repurposed to store the `why` object (or a new `why` column added and `why_tags` dropped). The API returns `why` instead of `why_tags`.

---

## Workstream 3 — Absolute match %

### Problem
`score_candidates` (scorer.py:52) min-max normalizes raw scores across the candidate pool, so the top film is always ~100% and the worst ~0%. A "hide below 70%" cutoff is meaningless.

### Change
Normalize each candidate's raw score against a **fixed theoretical maximum** of the weighted-sum scale (sum of weights × max normalized profile affinity = 1.0 per feature family, so the max achievable raw score is bounded and constant). `match_pct = clamp(raw / THEORETICAL_MAX * 100, 0, 100)`.

Tuned so a strong-but-imperfect match lands ~80–90%, a typical match ~60–75%. The constant lives in `scorer.py` and is adjustable. Percentages are now stable across refreshes and comparable across films, making the 70% cutoff real.

---

## Workstream 4 — Rich film-detail modal

### Change
Expand `WatchProvidersModal` into a full detail modal:
- Backdrop image (top), title, year, runtime, director.
- Synopsis (TMDB `overview`).
- Cast (top 5), genres.
- The specific reason (Workstream 2).
- Predicted ★ and match %.
- Where to watch (existing provider fetch), unchanged.

### Storage
`enrich()` (tmdb.py:11) already fetches the full movie object but discards `overview`, `runtime`, and `backdrop_path`. Keep them. Add columns to `films`: `backdrop_path`, `overview`, `runtime`. The recommendations API and a new/expanded film-detail response include them.

---

## Workstream 5 — Top Pick: Marquee spotlight trio

### Change
Replace the single hero band with a **"TONIGHT'S MARQUEE"** section: the top 3 recommendations as backdrop-image spotlight panels (first panel larger, `1.4fr 1fr 1fr`), each showing rank, title (Bebas Neue), match %, and reason. Below it, the rest of the list as the existing grid (subject to Workstream 7 caps). Uses `backdrop_path` from Workstream 4. Clicking a panel opens the rich modal.

---

## Workstream 6 — Taste Profile redesign (dashboard + radar + headshot wall)

Full redesign of `TasteProfilePage`. Modules, top to bottom:

1. **Stat row** — films rated, average ★ the user gives, favorite decade, top director.
2. **Rating-distribution histogram** — count of the user's ratings per ★ bucket (how generous a grader).
3. **Genre radar** — SVG spider chart of affinity across the main genres.
4. **Headshot wall** — top directors + actors as circular TMDB profile images with names/roles.
5. **Ranked affinity bars** — strongest affinities across genres/directors/keywords with proportional bars.
6. **Signature line** — one deterministic sentence assembled from the top features (e.g. "A tough grader with a neo-noir streak and a soft spot for 1970s auteurs.").

### Storage
Headshots require TMDB person `profile_path`. TMDB credits (already fetched in `enrich`) include `id` and `profile_path` for cast and crew — currently only the name is kept. Store person identity:
- New `people` table: `person_id` (TMDB), `name`, `profile_path`.
- `film_cast` / director references carry `person_id` so the taste page can join to `people` for headshots.
- Migration required; existing data must be re-refreshed (accepted).

### API
`/api/taste-profile` expands to return: totals, average rating, rating distribution, favorite decade, genre affinities (for radar), top directors and actors (name + profile_path), top keywords, and the signature string.

---

## Workstream 7 — List caps

- Recommendations sorted by absolute match % descending.
- **Main list**: top 25 (after the spotlight trio) shown by default; a "Show more" control reveals the remainder.
- **Long shots**: anything with match % below **70** is pulled into a separate collapsed "Long shots" section, out of the main flow.
- The API can return the full ordered list; the cap and split are applied client-side (simplest), or the API accepts a limit — decision deferred to the plan, default client-side.

---

## Data-model change summary

- `films`: add `backdrop_path`, `overview`, `runtime`.
- `people`: new table `(person_id, name, profile_path)`.
- `film_cast` and director storage: carry `person_id` to join to `people`.
- `recommendations`: `why_tags` → structured `why` (neighbor films + connection); `match_pct` now absolute.
- `enrich()`: retain `overview`, `runtime`, `backdrop_path`, and per-person `id` + `profile_path`.

Schema change means existing users must re-run a refresh. Accepted.

## Visual direction

Existing "Marquee Noir" system stays: near-black background, gold accent, Bebas Neue display type, Inter body. Both redesigned surfaces (spotlight trio, taste dashboard) follow it.

## Testing

- **Scraper**: unit test that a challenge/partial page raises rather than truncating; test that the completeness assertion fires on a count mismatch; test that a film with no TMDB id is still recorded as watched. Live verification against `moviefan` for the three named films.
- **Scorer**: test that reasons cite the nearest highly-rated neighbors and vary across candidates; test absolute match % is stable and bounded 0–100.
- **Taste profile API**: test the expanded response shape (distribution, affinities, people with profile_path, signature).
- **Frontend**: existing component tests updated for the new hero trio, rich modal, redesigned taste page, and list caps.
- Backend test suite (`backend/tests/`) stays green.

## Success criteria

1. A live refresh of `moviefan` produces recommendations containing **none** of the user's rated films; the three named films are confirmed excluded.
2. Every recommendation's reason names specific rated films and differs across films.
3. Match % is absolute and stable; the 70% cutoff cleanly separates the "Long shots" section.
4. Top Pick renders as the spotlight trio with real backdrops.
5. Clicking any film opens the rich modal with synopsis + detail + providers.
6. The Taste Profile page renders all six modules with real data and headshots.
7. The recommendations list caps at 25 with a working "Show more" and "Long shots" section.
