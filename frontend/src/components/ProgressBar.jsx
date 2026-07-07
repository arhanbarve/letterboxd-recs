import { useEffect, useRef, useState } from "react";

const STAGE_LABELS = {
  starting: "Starting...",
  scraping: "Scraping your Letterboxd ratings",
  enriching: "Fetching film details",
  profiling: "Building your taste profile",
  scoring: "Scoring candidates",
  done: "Done",
  error: "Something went wrong",
};

const STEP_INDEX = { starting: 1, scraping: 1, enriching: 2, profiling: 3, scoring: 4, done: 4 };
const TOTAL_STEPS = 4;

function formatClock(totalSeconds) {
  const s = Math.max(0, Math.round(totalSeconds));
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}:${String(rem).padStart(2, "0")}`;
}

export default function ProgressBar({ progress }) {
  const [now, setNow] = useState(() => Date.now());
  const startedAtRef = useRef(null);
  const stageRef = useRef(null);
  const stageStartRef = useRef(null);

  useEffect(() => {
    if (!progress) {
      startedAtRef.current = null;
      stageRef.current = null;
      stageStartRef.current = null;
      return;
    }
    if (startedAtRef.current === null) startedAtRef.current = Date.now();
    if (stageRef.current !== progress.stage) {
      stageRef.current = progress.stage;
      stageStartRef.current = Date.now();
    }
  }, [progress]);

  useEffect(() => {
    if (!progress || progress.stage === "done" || progress.stage === "error") return undefined;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [progress]);

  if (!progress) return null;
  const { stage, current, total, message } = progress;
  const determinate = typeof total === "number" && total > 0;
  const pct = determinate ? Math.min(100, Math.round((current / total) * 100)) : null;

  const elapsedSec = startedAtRef.current ? (now - startedAtRef.current) / 1000 : 0;
  const stageElapsedSec = stageStartRef.current ? Math.max(1, (now - stageStartRef.current) / 1000) : 1;

  let etaSec = null;
  if (determinate && current > 0 && current < total) {
    const rate = current / stageElapsedSec;
    if (rate > 0) etaSec = (total - current) / rate;
  }

  const step = STEP_INDEX[stage] || 0;

  return (
    <div className="progress-wrap" role="status" aria-live="polite">
      <div className="progress-label">
        {step > 0 && <span className="progress-step">Step {step}/{TOTAL_STEPS}</span>}
        <span>{STAGE_LABELS[stage] || stage}</span>
        {determinate && <span className="progress-count">{current}/{total} · {pct}%</span>}
      </div>
      <div className="progress-track">
        <div
          className={`progress-fill${determinate ? "" : " indeterminate"}`}
          style={determinate ? { width: `${pct}%` } : undefined}
        />
      </div>
      {stage !== "error" && (
        <div className="progress-meta">
          <span>Elapsed {formatClock(elapsedSec)}</span>
          {etaSec !== null && <span> · ~{formatClock(etaSec)} left</span>}
        </div>
      )}
      {stage === "scraping" && (
        <div className="progress-note">
          Letterboxd blocks fast scrapers, so this drives a real browser through each rated film —
          roughly 3–4s per film. Bigger profiles take longer; this is usually the slowest step.
        </div>
      )}
      {message && stage === "error" && <div className="progress-error">{message}</div>}
    </div>
  );
}
