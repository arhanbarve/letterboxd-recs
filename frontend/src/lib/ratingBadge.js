// Prefer IMDb, else RT, else TMDB fallback. Returns {label, value} or null.
// A TMDB score of 0 means "no votes yet" (e.g. unreleased films) — treat it as
// no data rather than showing a bogus "TMDB 0.0".
export function ratingBadge({ imdb_rating, rt_score, vote_avg }) {
  if (imdb_rating != null && imdb_rating > 0) return { label: "IMDb", value: imdb_rating.toFixed(1) };
  if (rt_score != null) return { label: "RT", value: `${rt_score}%` };
  if (vote_avg != null && vote_avg > 0) return { label: "TMDB", value: vote_avg.toFixed(1) };
  return null;
}
