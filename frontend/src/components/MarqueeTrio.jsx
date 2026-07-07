const BACKDROP = "https://image.tmdb.org/t/p/w1280";

function TrioPanel({ rec, rank, onSelect }) {
  return (
    <div
      className={`trio-panel trio-rank-${rank}`}
      style={rec.backdrop_path ? { backgroundImage: `url(${BACKDROP}${rec.backdrop_path})` } : undefined}
      role="button"
      tabIndex={0}
      onClick={() => onSelect(rec)}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onSelect(rec))}
    >
      <div className="trio-scrim" />
      <div className="trio-content">
        <div className="trio-rank-label">#{rank}</div>
        <div className="trio-title">
          {rec.title} <span className="trio-year">({rec.year})</span>
        </div>
        <div className="trio-match">{Math.round(rec.match_pct)}% match</div>
      </div>
    </div>
  );
}

export default function MarqueeTrio({ recs, onSelect }) {
  if (!recs || recs.length === 0) return null;
  return (
    <div className="marquee-trio-section">
      <div className="marquee-eyebrow">Tonight's Marquee</div>
      <div className="marquee-trio">
        {recs.map((rec, i) => (
          <TrioPanel key={rec.tmdb_id} rec={rec} rank={i + 1} onSelect={onSelect} />
        ))}
      </div>
    </div>
  );
}
