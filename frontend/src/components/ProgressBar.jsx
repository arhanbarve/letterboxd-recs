import { useEffect, useRef, useState } from "react";
import { computePercent, computeEtaSec, monotonicPercent, formatClock } from "../lib/progressMath";

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

export default function ProgressBar({ status }) {
  const [now, setNow] = useState(() => Date.now());
  const startedAtRef = useRef(null);
  const stageRef = useRef(null);
  const stageStartRef = useRef(null);
  const maxPercentRef = useRef(0);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (!status) {
      startedAtRef.current = null;
      stageRef.current = null;
      stageStartRef.current = null;
      maxPercentRef.current = 0;
      return;
    }
    if (startedAtRef.current === null) startedAtRef.current = Date.now();
    if (stageRef.current !== status.stage) {
      stageRef.current = status.stage;
      stageStartRef.current = Date.now();
    }
  }, [status]);

  if (!status) return null;
  const { stage, message } = status;

  const stageElapsedMs = stageStartRef.current ? now - stageStartRef.current : 0;
  const totalElapsedSec = startedAtRef.current ? (now - startedAtRef.current) / 1000 : 0;

  const rawPercent = computePercent(status, { stageElapsedMs });
  const percent = monotonicPercent(rawPercent, maxPercentRef.current);
  maxPercentRef.current = percent;

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
