function pointFor(angle, radius, cx, cy) {
  return [cx + radius * Math.cos(angle), cy + radius * Math.sin(angle)];
}

export default function GenreRadar({ genres }) {
  const top = genres.slice(0, 6);
  if (top.length < 3) return null;

  const size = 220;
  const cx = size / 2;
  const cy = size / 2;
  const maxRadius = size / 2 - 24;
  const step = (2 * Math.PI) / top.length;

  const maxAffinity = Math.max(...top.map((g) => Math.max(g.affinity, 0)), 0.01);
  const points = top.map((g, i) => {
    const angle = -Math.PI / 2 + i * step;
    const r = (Math.max(g.affinity, 0) / maxAffinity) * maxRadius;
    return pointFor(angle, r, cx, cy);
  });
  const polygon = points.map(([x, y]) => `${x},${y}`).join(" ");

  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="genre-radar" role="img" aria-label="Genre affinity radar">
      {[0.33, 0.66, 1].map((f) => (
        <polygon
          key={f}
          points={top.map((_, i) => pointFor(-Math.PI / 2 + i * step, maxRadius * f, cx, cy).join(",")).join(" ")}
          className="radar-grid"
        />
      ))}
      <polygon points={polygon} className="radar-shape" />
      {top.map((g, i) => {
        const [lx, ly] = pointFor(-Math.PI / 2 + i * step, maxRadius + 14, cx, cy);
        return (
          <text key={g.name} x={lx} y={ly} className="radar-label" textAnchor="middle">
            {g.name}
          </text>
        );
      })}
    </svg>
  );
}
