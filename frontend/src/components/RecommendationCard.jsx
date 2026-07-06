import { useState } from "react";
import { useCountUp } from "../lib/useCountUp";

const IMG = "https://image.tmdb.org/t/p/w300";

export default function RecommendationCard({ rec, index = 0, onSelect }) {
  const match = useCountUp(rec.match_pct);
  const predicted = useCountUp(rec.predicted_rating);
  const [imgFailed, setImgFailed] = useState(false);

  return (
    <div
      className="card"
      style={{ animationDelay: `${index * 60}ms` }}
      role="button"
      tabIndex={0}
      onClick={() => onSelect(rec)}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onSelect(rec))}
    >
      <div className="card-poster">
        {rec.poster_path && !imgFailed ? (
          <img
            src={IMG + rec.poster_path}
            alt={rec.title}
            loading="lazy"
            onError={() => setImgFailed(true)}
          />
        ) : (
          <div className="card-poster-placeholder">No poster</div>
        )}
      </div>
      <div className="card-body">
        <h3 className="card-title">
          {rec.title} <span className="card-meta">({rec.year})</span>
        </h3>
        <div className="card-stats">
          <span className="card-match">{Math.round(match)}% match</span>
          <span className="card-predicted">{predicted.toFixed(1)}★ predicted</span>
        </div>
        {rec.why_tags?.length > 0 && (
          <p className="card-why">Because you like: {rec.why_tags.join(", ")}</p>
        )}
      </div>
    </div>
  );
}
