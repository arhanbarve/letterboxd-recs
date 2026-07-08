import { useEffect, useState } from "react";
import { computePercent, computeEtaSec, monotonicPercent, formatClock } from "../lib/progressMath";
import { useRefresh } from "../context/RefreshContext";

const STAGE_LABELS = {
  starting: "Starting...",
  scraping: "Scraping your Letterboxd ratings",
  enriching: "Fetching film details",
  profiling: "Building your taste profile",
  scoring: "Scoring candidates",
  done: "Done",
  cancelled: "Cancelled",
  error: "Something went wrong",
};

const STEP_INDEX = { starting: 1, scraping: 1, enriching: 2, profiling: 3, scoring: 4, done: 4 };
const TOTAL_STEPS = 4;

export default function ProgressBar() {
  const { status, timing } = useRefresh();
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const stageElapsedMs = status && timing.stageStartRef.current ? now - timing.stageStartRef.current : 0;
  const totalElapsedSec = status && timing.startedAtRef.current ? (now - timing.startedAtRef.current) / 1000 : 0;
  const rawPercent = status ? computePercent(status, { stageElapsedMs }) : 0;
  const percent = monotonicPercent(rawPercent, timing.maxPercentRef.current);

  useEffect(() => {
    timing.maxPercentRef.current = percent;
  }, [percent, timing]);

  if (!status) return null;
  const { stage, message } = status;

  const etaSec = stage === "cancelled" || stage === "error" ? null : computeEtaSec(status, { stageElapsedMs });
  const step = STEP_INDEX[stage] || 0;

  return (
    <div className="progress-wrap" role="status" aria-live="polite">
      <div className="progress-label">
        {step > 0 && <span className="progress-step">Step {step}/{TOTAL_STEPS}</span>}
        <span>{STAGE_LABELS[stage] || stage}</span>
        <span className="progress-count">{Math.round(percent)}%</span>
      </div>
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${percent}%` }} />
      </div>
      {stage !== "error" && (
        <div className="progress-meta">
          <span>Elapsed {formatClock(totalElapsedSec)}</span>
          {etaSec !== null && <span> · ~{formatClock(etaSec)} left</span>}
        </div>
      )}
      {stage === "scraping" && (
        <div className="progress-note">
          Letterboxd throttles scraping — roughly 3–4s per film, longer for bigger profiles.
        </div>
      )}
      {message && stage === "error" && <div className="progress-error">{message}</div>}
    </div>
  );
}
