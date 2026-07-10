import { describe, it, expect } from "vitest";
import { partitionRecs } from "./recList";

const mk = (n, pct) => Array.from({ length: n }, (_, i) => ({ tmdb_id: i, match_pct: pct }));

describe("partitionRecs", () => {
  it("hero is the first three", () => {
    const { hero } = partitionRecs(mk(30, 80));
    expect(hero.map((r) => r.tmdb_id)).toEqual([0, 1, 2]);
  });
  it("main holds all >=60% after the hero", () => {
    const recs = [...mk(3, 95), ...mk(25, 72), ...mk(40, 30)];
    const { main, longShots } = partitionRecs(recs);
    expect(main.length).toBe(25);
    expect(longShots.length).toBe(40);
  });
  it("main is padded to at least 20 when few clear the bar", () => {
    const recs = [...mk(3, 95), ...mk(2, 72), ...mk(40, 30)];
    const { main } = partitionRecs(recs);
    expect(main.length).toBe(20);
  });
  it("never exceeds available when total is small", () => {
    const recs = mk(8, 40);
    const { hero, main, longShots } = partitionRecs(recs);
    expect(hero.length + main.length + longShots.length).toBe(8);
    expect(main.length).toBe(5); // 8 - 3 hero, min(20, 5)
  });
});
