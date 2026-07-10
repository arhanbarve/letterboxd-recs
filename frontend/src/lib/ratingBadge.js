// Prefer IMDb, else RT, else TMDB fallback. Returns {label, value} or null.
export function ratingBadge({ imdb_rating, rt_score, vote_avg }) {
  if (imdb_rating != null) return { label: "IMDb", value: imdb_rating.toFixed(1) };
  if (rt_score != null) return { label: "RT", value: `${rt_score}%` };
  if (vote_avg != null) return { label: "TMDB", value: vote_avg.toFixed(1) };
  return null;
}
