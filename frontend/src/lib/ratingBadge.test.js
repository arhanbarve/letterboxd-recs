import { describe, it, expect } from "vitest";
import { ratingBadge } from "./ratingBadge";

describe("ratingBadge", () => {
  it("prefers IMDb", () => {
    expect(ratingBadge({ imdb_rating: 8.1, rt_score: 90, vote_avg: 7.2 })).toEqual({ label: "IMDb", value: "8.1" });
  });
  it("falls back to RT then TMDB", () => {
    expect(ratingBadge({ imdb_rating: null, rt_score: 90, vote_avg: 7.2 })).toEqual({ label: "RT", value: "90%" });
    expect(ratingBadge({ imdb_rating: null, rt_score: null, vote_avg: 7.2 })).toEqual({ label: "TMDB", value: "7.2" });
  });
  it("treats a zero TMDB score as no data (no bogus TMDB 0.0)", () => {
    expect(ratingBadge({ imdb_rating: null, rt_score: null, vote_avg: 0 })).toBeNull();
    expect(ratingBadge({ imdb_rating: 0, rt_score: null, vote_avg: 0 })).toBeNull();
  });
  it("returns null when nothing is present", () => {
    expect(ratingBadge({})).toBeNull();
  });
});
