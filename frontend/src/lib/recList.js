export function partitionRecs(recs, { mainThreshold = 60, minMain = 20 } = {}) {
  const hero = recs.slice(0, 3);
  const rest = recs.slice(3);
  let n = rest.filter((r) => r.match_pct >= mainThreshold).length;
  n = Math.max(n, Math.min(minMain, rest.length));
  return { hero, main: rest.slice(0, n), longShots: rest.slice(n) };
}
