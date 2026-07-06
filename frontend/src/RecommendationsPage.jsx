import { useEffect, useState } from "react";
import { getRecommendations, refresh } from "./api";

const IMG = "https://image.tmdb.org/t/p/w200";

export default function RecommendationsPage() {
  const [recs, setRecs] = useState([]);
  const [loading, setLoading] = useState(false);

  const load = () => getRecommendations().then(setRecs);
  useEffect(() => { load(); }, []);

  const onRefresh = async () => {
    setLoading(true);
    await refresh();
    await load();
    setLoading(false);
  };

  return (
    <div>
      <button onClick={onRefresh} disabled={loading}>
        {loading ? "Refreshing…" : "Refresh my data"}
      </button>
      <div className="rec-grid">
        {recs.map((r) => (
          <div key={r.tmdb_id} className="rec-card">
            {r.poster_path && <img src={IMG + r.poster_path} alt={r.title} />}
            <h3>{r.title} ({r.year})</h3>
            <p>{r.predicted_rating}★ predicted · {r.match_pct}% match</p>
            <p className="why">Because you like: {r.why_tags.join(", ")}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
