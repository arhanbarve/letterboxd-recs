import { useRef, useState } from "react";
import { useCountUp } from "../lib/useCountUp";
import { ratingBadge } from "../lib/ratingBadge";

const IMG = "https://image.tmdb.org/t/p/w300";

export default function RecommendationCard({ rec, index = 0, onSelect }) {
  const match = useCountUp(rec.match_pct);
  const [imgFailed, setImgFailed] = useState(false);
  const ref = useRef(null);
  const badge = ratingBadge(rec);

  const onMove = (e) => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width - 0.5;
    const py = (e.clientY - r.top) / r.height - 0.5;
    el.style.setProperty("--rx", `${(-py * 8).toFixed(2)}deg`);
    el.style.setProperty("--ry", `${(px * 10).toFixed(2)}deg`);
  };
  const onLeave = () => {
    const el = ref.current;
    if (!el) return;
    el.style.setProperty("--rx", "0deg");
    el.style.setProperty("--ry", "0deg");
  };

  return (
    <div
      ref={ref}
      className="card tilt"
      style={{ animationDelay: `${index * 50}ms` }}
      role="button"
      tabIndex={0}
      onMouseMove={onMove}
      onMouseLeave={onLeave}
      onClick={() => onSelect(rec)}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onSelect(rec))}
    >
      <div className="card-inner">
        <div className="card-poster">
          {rec.poster_path && !imgFailed ? (
            <img src={IMG + rec.poster_path} alt={rec.title} loading="lazy" onError={() => setImgFailed(true)} />
          ) : (
            <div className="card-poster-placeholder">No poster</div>
          )}
          {badge && <span className="rating-badge">{badge.label} {badge.value}</span>}
        </div>
        <div className="card-body">
          <h3 className="card-title">{rec.title} <span className="card-meta">({rec.year})</span></h3>
          {rec.starring?.length > 0 && (
            <p className="card-starring">{rec.starring.join(", ")}</p>
          )}
          <div className="card-stats">
            <span className="card-match">{Math.round(match)}% match</span>
            <span className="card-predicted">{rec.predicted_rating?.toFixed(1)}★ predicted</span>
          </div>
        </div>
      </div>
    </div>
  );
}
