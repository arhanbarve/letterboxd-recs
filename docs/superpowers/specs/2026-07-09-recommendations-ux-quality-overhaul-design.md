# Recommendations UX + Quality Overhaul — Design

Date: 2026-07-09
Status: Approved (brainstorming + grilling complete)

## Problem

The recommender works end-to-end but the front end and scoring have concrete
defects and gaps:

1. No notion of a film's *critical quality* — an objectively panned film can be
   recommended purely because it resembles films the user likes.
2. Only the top 3 + a `>=70%` list are surfaced; the user wants a real list
   (min 20) and paginated long shots.
3. Match% tops out near 50% because raw affinity averages sit low; the number
   reads as weak even for the best pick.
4. The film-detail modal is visually broken: a black bar (a `margin:-24px`
   backdrop hack), content cut off / anchored to the top, no clear back
   control, and non-functional after opening long-shot cards until reload.
5. The hero trio hides the predicted rating that the rest of the cards show.
6. "Tonight's Marquee" naming; user wants it renamed.
7. Long shots render *all* rows at once → infinitely long page.
8. Cards omit the cast ("starring").
9. Flat visual language — user wants snappy, futuristic card motion.
10. Username field and Refresh button are on separate rows; home layout is
    unfocused.
11. Taste Profile is a tab, not its own URL.
12. Header is plain text ("Letterboxd Recs by Arhan").
13. Taste Profile content is left-aligned, not centered; rating histogram is in
    whole-star buckets though Letterboxd rates in 0.5 steps; headers are too
    small; the gap under the username row is too tight.
14. Genre radar is limited (6 axes) and visually plain.
15. Director/actor names are mis-centered; no way to see *which* films drive
    each person's ranking.

## Decisions (locked via grilling)

| # | Decision | Choice |
|---|----------|--------|
| Hero name | rename "Tonight's Marquee" | **Tonight's Feature** |
| Quality source | where critical scores come from | **Hybrid**: TMDB `vote_average` gates *all* candidates (free, already fetched); OMDb (IMDb + Rotten Tomatoes) fetched only for the top ~80 stored recs per refresh |
| Quality effect | how quality changes recs | **Floor + soft penalty** |
| Floor strictness | which films are excluded | **Balanced**: `vote_count >= 50 AND vote_avg < 5.0` → excluded; sparse-vote films kept but get no quality boost |
| Match% method | scaling | **Anchored-absolute**: 95% anchor = median raw score of the user's own 4.5★+ films scored against their profile; honest + stable across refreshes |
| List shape | grid vs long shots | **Quality cut + floor**: hero top-3 → main grid = matches `>=60%` but never fewer than 20 → "Load long shots" reveals the weaker tail 50 per click |
| Card motion | animation model | **Tilt + glow on hover; click flips + expands the card to center** |
| Detail view | modal replacement | The **expanded center card is the full detail view** — replaces the old modal entirely and holds everything incl. streaming providers |
| Missing rating | OMDb miss / pre-refresh | **Fall back to TMDB rating** (labeled `TMDB 7.4`) |
| Header | brand | **Marquee bulb sign**: `REEL` wordmark ringed by glowing bulbs, subtle flicker; `by arhan` subtitle |
| Radar | complexity | **10 axes**, concentric ring grid, gradient fill, value ticks, hover shows exact affinity |
| People reveal | hover behavior | **Hover (desktop) + tap (mobile)** pops the user's top-3 highest-rated films for that person |
| Long-shots page | chunk size | **50 per click** |

## Architecture

### Routing & shell (frontend)
- Add `react-router-dom`. Routes: `/` → Recommendations, `/taste` → Taste
  Profile. Tabs become `NavLink`s; browser back/forward and deep links work.
- New `BulbSign` header component (marquee bulbs + `REEL` + `by arhan`), sits
  above the nav. Flicker/glow animation disabled under
  `prefers-reduced-motion`.
- Home control row: `UsernameField` + `RefreshButton` on **one line**
  (flex, `justify-content: space-between`, wraps on narrow screens).
  Recommendations render below.

### Backend — quality signal
- `tmdb.enrich()` additionally requests `external_ids` and captures
  `imdb_id` and `vote_count`.
- New module `app/omdb.py`:
  - `fetch_ratings(imdb_id, api_key, session=None) -> {"imdb_rating": float|None, "rt_score": int|None}`
  - Parses OMDb `imdbRating` and the `Ratings` array (Rotten Tomatoes = the
    `"Internet Movie Database"` / `"Rotten Tomatoes"` entries). Timeout +
    retry mirroring `tmdb._get`. Returns `None`s on failure (never raises into
    the pipeline).
- `app/config.py`: add `omdb_api_key` from `OMDB_API_KEY` (optional; when
  absent the pipeline simply skips OMDb and every card uses the TMDB fallback).
- `db.py` schema + migrations: add nullable columns on `films`:
  `vote_count INTEGER`, `imdb_rating REAL`, `rt_score INTEGER`.
- Pipeline: after scoring, for the **top ~80** results by final match, resolve
  each film's `imdb_id` and call `omdb.fetch_ratings`, storing
  `imdb_rating`/`rt_score` on the film row. Bounded ≈80 OMDb calls/refresh
  (free tier = 1000/day). Failures are individually swallowed.

### Backend — scoring changes (`scorer.py`)
- **Quality gate + factor** computed from `vote_avg` / `vote_count`:
  - Exclude candidate when `vote_count >= 50 and vote_avg < 5.0`.
  - `quality_factor(vote_avg)`: linear map of `vote_avg` 5.0→8.5 onto
    ~0.85→1.12, clamped; sparse-vote films (`vote_count < 50` or missing) →
    factor `1.0` (neutral, no boost/penalty).
- **Anchored-absolute match%**:
  - Compute `anchor_raw` = median of `match_raw_score(f, profile)` over the
    user's rated films with `rating >= 4.5` (fallback to `>=4.0`, then to the
    max candidate raw if the user has too few high ratings).
  - `match_pct = clamp( (raw / anchor_raw) * 95, 0, 99 )`, then floor the
    *displayed* value so shown films read sensibly (final ordering uses
    `raw * quality_factor`).
  - Ordering key = `raw * quality_factor` (quality tilts ranking; excluded
    films removed first).
- `score_candidates` signature gains the candidate `vote_avg`/`vote_count`
  (already present on enriched dicts via `vote_avg`; add `vote_count`).

### Backend — payload additions
- `GET /api/recommendations`: add `starring` (top-3 cast via `film_cast`),
  `imdb_rating`, `rt_score`, `vote_avg` per row.
- `taste_dashboard._rating_distribution`: 10 buckets in 0.5 steps
  (0.5–5.0) instead of 5 whole-star buckets. Bucket = round to nearest 0.5.
- `taste_dashboard`: `genre_affinities` returns top ~10 (radar/affinity use it).
- `taste_dashboard`: each entry in `top_directors` / `top_actors` gains
  `top_films`: the user's 3 highest-rated films for that person
  `[{title, year, rating, poster_path}]` (JOIN `ratings` + `films`, order by
  `your_rating` desc, limit 3).

### Frontend — Recommendations page
- Rename hero component copy to **Tonight's Feature**; each hero panel adds
  predicted `★`.
- Partition:
  - `hero` = first 3.
  - `main` = of the rest, all with `match_pct >= 60`, but if fewer than 20
    qualify, extend to the first 20.
  - `longShots` = remainder; hidden behind "Load long shots", revealed 50 at a
    time (its own `visibleCount`, `+50` per click).
- **Card** (`RecommendationCard`): two faces.
  - Front: poster, title (year), `starring …`, match%, predicted ★,
    IMDb/RT (or TMDB fallback) badge.
  - Back (revealed on flip): why ("because you loved …"), scores, and a
    "Where to watch →" affordance.
  - Hover: pointer-tracked 3D tilt + accent glow.
  - Click: flip + **expand to center** (shared-element grow) into the full
    detail view.
- **Expanded detail card** (replaces `FilmDetailModal`): backdrop hero,
  title/year/starring, match% + predicted, IMDb + RT (fallback TMDB),
  "because you loved …" with neighbor posters, overview, genres,
  runtime/director, streaming providers + links. Internal scroll if tall.
  Backdrop bug fixed (no negative-margin hack; image is a contained hero).
  Esc / ✕ / backdrop-click / browser-back all collapse it.
- **Long-shot open bug**: reproduce with Playwright, root-cause, fix (suspected
  interaction between the collapsed-section render and card mount). Verified by
  opening a long-shot card without a page reload.

### Frontend — Taste Profile page
- `.taste-dashboard` centered (`margin: 0 auto`) with a wider top gap.
- Section headers and "Your Taste Fingerprint" scaled up (display type, more
  prominent site-wide).
- Rating histogram: 10 half-star bars with 0.5-step labels.
- `GenreRadar`: 10 axes, ring grid, gradient fill, value ticks, hover reads the
  exact affinity value.
- People walls: names centered; hover (desktop) / tap (mobile) pops a popover
  of the user's top-3 films for that person (poster + rating).

### Frontend — motion & performance
- All animations use `transform`/`opacity` only (tilt, flip, expand, glow,
  entrance stagger). No layout-thrashing properties.
- Everything degrades under `prefers-reduced-motion`: no tilt/flip/flicker;
  expand becomes an instant show.
- Tilt uses a pointer handler throttled to `requestAnimationFrame`.

## Testing
- **Backend**: unit tests for `omdb.fetch_ratings` (parse + failure), quality
  gate/factor and anchored match% in `scorer`, half-star distribution and
  `top_films` in `taste_dashboard`, and the enriched `/api/recommendations`
  payload.
- **Frontend**: existing `progressMath` tests stay green; add coverage for the
  list partition (min-20, `>=60%`, long-shot slicing).
- **Playwright** (end-to-end, per user request): header renders; username +
  refresh on one line; recs list ≥20; hero shows predicted; card tilt + flip +
  expand-to-center works; long-shot card opens without reload; `/taste` is a
  real URL, centered, half-star histogram, 10-axis radar, people hover reveal.

## Out of scope
- Scraper / proxy infrastructure (unchanged).
- No new recommendation *algorithm* beyond the quality gate/factor and %
  recalibration.
- OMDb for *every* candidate (rate-limit risk) — only top ~80 shown films.

## Risks / assumptions
- OMDb free key required for IMDb/RT; without it everything falls back to TMDB
  (still fully functional).
- Anchored match% depends on the user having a few 4.5★+ ratings; fallbacks
  cover sparse cases.
- Quality gate uses TMDB, not IMDb, for the floor (IMDb unavailable for all
  candidates within rate limits); TMDB/IMDb correlate strongly.
- Expand-to-center replaces the modal; the old `FilmDetailModal` component is
  removed.
