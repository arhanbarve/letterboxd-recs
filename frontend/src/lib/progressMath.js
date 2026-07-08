export const STAGE_BANDS = {
  scraping: [0, 55],
  enriching: [55, 80],
  profiling: [80, 86],
  scoring: [86, 99],
  done: [99, 100],
};

const DETERMINATE_STAGES = new Set(["enriching", "scoring"]);

// Constants driving the "fake but honest" creep for indeterminate stages
// and the ETA guess for stages with no live count yet. Real counts always
// override these once the backend reports them.
const SEC_PER_FILM_SCRAPE = 3.5;
const SCRAPE_BASE_ESTIMATE_SEC = 45;
const PROFILING_ESTIMATE_SEC = 8;
const SCORING_FALLBACK_ESTIMATE_SEC = 20;
const FLAT_ESTIMATE_SEC = { profiling: PROFILING_ESTIMATE_SEC };

function bandFor(stage) {
  return STAGE_BANDS[stage] || STAGE_BANDS.scraping;
}

function estimateStageDurationSec(stage, status) {
  if (stage === "scraping") {
    const found = status.current || 0;
    return Math.max(SCRAPE_BASE_ESTIMATE_SEC, found * SEC_PER_FILM_SCRAPE * 1.6);
  }
  if (stage === "profiling") return PROFILING_ESTIMATE_SEC;
  if (stage === "scoring") return SCORING_FALLBACK_ESTIMATE_SEC;
  return SCRAPE_BASE_ESTIMATE_SEC;
}

function creepFraction(elapsedSec, estimatedSec) {
  if (estimatedSec <= 0) return 0.96;
  const ratio = elapsedSec / estimatedSec;
  return Math.max(0, Math.min(0.96, 1 - Math.exp(-ratio * 1.5)));
}

export function computePercent(status, { stageElapsedMs = 0 } = {}) {
  const stage = status.stage;
  if (stage === "done") return 100;
  if (stage === "error" || stage === "cancelled" || (!STAGE_BANDS[stage] && stage !== "scraping")) {
    return 0;
  }
  const [floor, ceil] = bandFor(stage);
  const determinateReady = DETERMINATE_STAGES.has(stage) && typeof status.total === "number" && status.total > 0 && typeof status.current === "number";
  if (determinateReady) {
    const frac = Math.min(1, Math.max(0, status.current / status.total));
    return floor + frac * (ceil - floor);
  }
  const estSec = estimateStageDurationSec(stage, status);
  const frac = creepFraction(stageElapsedMs / 1000, estSec);
  return floor + frac * (ceil - floor);
}

export function monotonicPercent(rawPercent, prevMaxPercent) {
  return Number.isFinite(rawPercent) ? Math.max(rawPercent, prevMaxPercent) : prevMaxPercent;
}

const STAGE_ORDER = ["scraping", "enriching", "profiling", "scoring"];

export function computeEtaSec(status, { stageElapsedMs = 0 } = {}) {
  const stage = status.stage;
  if (stage === "done" || stage === "error" || stage === "cancelled") return null;
  const idx = STAGE_ORDER.indexOf(stage);
  if (idx === -1) return null;

  let remaining = 0;
  for (let i = idx; i < STAGE_ORDER.length; i++) {
    const s = STAGE_ORDER[i];
    if (s === stage) {
      if (DETERMINATE_STAGES.has(s) && typeof status.total === "number" && status.total > 0 && status.current > 0) {
        const rate = status.current / Math.max(1, stageElapsedMs / 1000);
        remaining += rate > 0 ? (status.total - status.current) / rate : estimateStageDurationSec(s, status);
      } else {
        const est = estimateStageDurationSec(s, status);
        remaining += Math.max(0, est - stageElapsedMs / 1000);
      }
    } else {
      remaining += FLAT_ESTIMATE_SEC[s] ?? estimateStageDurationSec(s, status);
    }
  }
  return remaining;
}

export function formatClock(totalSeconds) {
  const s = Math.max(0, Math.round(totalSeconds));
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}:${String(rem).padStart(2, "0")}`;
}
