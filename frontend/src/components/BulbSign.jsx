export default function BulbSign() {
  return (
    <div className="bulb-sign" aria-label="REEL — recommendations by Arhan">
      <div className="bulb-row" aria-hidden="true">
        {Array.from({ length: 14 }).map((_, i) => (
          <span className="bulb" style={{ "--i": i }} key={i} />
        ))}
      </div>
      <div className="bulb-wordmark">
        <span className="bulb-title">REEL</span>
        <span className="bulb-sub">by arhan</span>
      </div>
      <div className="bulb-row" aria-hidden="true">
        {Array.from({ length: 14 }).map((_, i) => (
          <span className="bulb" style={{ "--i": i }} key={i} />
        ))}
      </div>
    </div>
  );
}
