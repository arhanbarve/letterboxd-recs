const STAGE_LABELS = {
  starting: "Starting...",
  scraping: "Scraping your Letterboxd ratings",
  enriching: "Fetching film details",
  profiling: "Building your taste profile",
  scoring: "Scoring candidates",
  done: "Done",
  error: "Something went wrong",
};

export default function ProgressBar({ progress }) {
  if (!progress) return null;
  const { stage, current, total, message } = progress;
  const determinate = typeof total === "number" && total > 0;
  const pct = determinate ? Math.min(100, Math.round((current / total) * 100)) : null;

  return (
    <div className="progress-wrap" role="status" aria-live="polite">
      <div className="progress-label">
        {STAGE_LABELS[stage] || stage}
        {determinate && <span className="progress-count"> · {current}/{total}</span>}
      </div>
      <div className="progress-track">
        <div
          className={`progress-fill${determinate ? "" : " indeterminate"}`}
          style={determinate ? { width: `${pct}%` } : undefined}
        />
      </div>
      {message && stage === "error" && <div className="progress-error">{message}</div>}
    </div>
  );
}
