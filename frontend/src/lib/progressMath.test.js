import { describe, it, expect } from "vitest";
import { computePercent, computeEtaSec, monotonicPercent, formatClock, STAGE_BANDS } from "./progressMath";

describe("STAGE_BANDS", () => {
  it("covers every pipeline stage with a non-overlapping, ascending band", () => {
    const order = ["scraping", "enriching", "profiling", "scoring", "done"];
    let prevCeil = 0;
    for (const stage of order) {
      const [floor, ceil] = STAGE_BANDS[stage];
      expect(floor).toBe(prevCeil);
      expect(ceil).toBeGreaterThanOrEqual(floor);
      prevCeil = ceil;
    }
    expect(prevCeil).toBe(100);
  });
});

describe("computePercent", () => {
  it("returns 100 for done", () => {
    expect(computePercent({ stage: "done", current: 5, total: 5 }, {})).toBe(100);
  });

  it("interpolates determinate enriching stage linearly within its band", () => {
    const [floor, ceil] = STAGE_BANDS.enriching;
    const pct = computePercent({ stage: "enriching", current: 5, total: 10 }, { stageElapsedMs: 0 });
    expect(pct).toBeCloseTo(floor + 0.5 * (ceil - floor), 5);
  });

  it("interpolates determinate scoring stage linearly within its band", () => {
    const [floor, ceil] = STAGE_BANDS.scoring;
    const pct = computePercent({ stage: "scoring", current: 3, total: 12 }, { stageElapsedMs: 0 });
    expect(pct).toBeCloseTo(floor + (3 / 12) * (ceil - floor), 5);
  });

  it("creeps toward but never reaches the scraping band ceiling as time passes", () => {
    const [, ceil] = STAGE_BANDS.scraping;
    const early = computePercent({ stage: "scraping", current: 0, total: null }, { stageElapsedMs: 1000 });
    const later = computePercent({ stage: "scraping", current: 0, total: null }, { stageElapsedMs: 120000 });
    expect(later).toBeGreaterThan(early);
    expect(later).toBeLessThan(ceil);
  });

  it("creeps toward but never reaches the profiling band ceiling", () => {
    const [, ceil] = STAGE_BANDS.profiling;
    const pct = computePercent({ stage: "profiling", current: 0, total: null }, { stageElapsedMs: 600000 });
    expect(pct).toBeLessThan(ceil);
  });

  it("never returns a percent below the stage floor", () => {
    const [floor] = STAGE_BANDS.scoring;
    const pct = computePercent({ stage: "scoring", current: 0, total: 100 }, { stageElapsedMs: 0 });
    expect(pct).toBeGreaterThanOrEqual(floor);
  });
});

describe("monotonicPercent", () => {
  it("never rewinds even if the raw computation dips", () => {
    expect(monotonicPercent(40, 60)).toBe(60);
    expect(monotonicPercent(70, 60)).toBe(70);
  });

  it("holds steady across a full scripted run", () => {
    const sequence = [
      { stage: "scraping", current: 0, total: null, stageElapsedMs: 0 },
      { stage: "scraping", current: 0, total: null, stageElapsedMs: 5000 },
      { stage: "enriching", current: 0, total: 20, stageElapsedMs: 0 },
      { stage: "enriching", current: 10, total: 20, stageElapsedMs: 5000 },
      { stage: "enriching", current: 20, total: 20, stageElapsedMs: 10000 },
      { stage: "profiling", current: 0, total: null, stageElapsedMs: 0 },
      { stage: "scoring", current: 0, total: 15, stageElapsedMs: 0 },
      { stage: "scoring", current: 15, total: 15, stageElapsedMs: 8000 },
      { stage: "done", current: 15, total: 15, stageElapsedMs: 0 },
    ];
    let max = 0;
    for (const s of sequence) {
      const raw = computePercent(s, { stageElapsedMs: s.stageElapsedMs });
      const displayed = monotonicPercent(raw, max);
      expect(displayed).toBeGreaterThanOrEqual(max);
      max = displayed;
    }
    expect(max).toBe(100);
  });
});

describe("computeEtaSec", () => {
  it("returns null once done", () => {
    expect(computeEtaSec({ stage: "done", current: 5, total: 5 }, {})).toBeNull();
  });

  it("returns null on error or cancelled", () => {
    expect(computeEtaSec({ stage: "error", current: 0, total: null }, {})).toBeNull();
    expect(computeEtaSec({ stage: "cancelled", current: 0, total: null }, {})).toBeNull();
  });

  it("is positive during an in-progress determinate stage", () => {
    const eta = computeEtaSec({ stage: "enriching", current: 2, total: 20 }, { stageElapsedMs: 4000 });
    expect(eta).toBeGreaterThan(0);
  });

  it("shrinks as a determinate stage nears completion at a constant rate", () => {
    const early = computeEtaSec({ stage: "enriching", current: 2, total: 20 }, { stageElapsedMs: 4000 });
    const late = computeEtaSec({ stage: "enriching", current: 18, total: 20 }, { stageElapsedMs: 36000 });
    expect(late).toBeLessThan(early);
  });
});

describe("formatClock", () => {
  it("formats seconds as m:ss", () => {
    expect(formatClock(5)).toBe("0:05");
    expect(formatClock(65)).toBe("1:05");
    expect(formatClock(0)).toBe("0:00");
  });

  it("floors negative input to zero", () => {
    expect(formatClock(-3)).toBe("0:00");
  });
});
