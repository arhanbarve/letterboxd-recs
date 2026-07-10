import { useState } from "react";

function pointFor(angle, radius, cx, cy) {
  return [cx + radius * Math.cos(angle), cy + radius * Math.sin(angle)];
}

export default function GenreRadar({ genres }) {
  const top = genres.slice(0, 10);
  const [hover, setHover] = useState(null);
  if (top.length < 3) return null;

  const size = 300, cx = size / 2, cy = size / 2, maxRadius = size / 2 - 40;
  const step = (2 * Math.PI) / top.length;
  const maxAff = Math.max(...top.map((g) => Math.max(g.affinity, 0)), 0.01);
  const pts = top.map((g, i) => {
    const a = -Math.PI / 2 + i * step;
    return pointFor(a, (Math.max(g.affinity, 0) / maxAff) * maxRadius, cx, cy);
  });
  const polygon = pts.map(([x, y]) => `${x},${y}`).join(" ");

  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="genre-radar" role="img" aria-label="Genre affinity radar">
      <defs>
        <radialGradient id="radar-fill">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.45" />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.08" />
        </radialGradient>
      </defs>
      {[0.25, 0.5, 0.75, 1].map((f) => (
        <polygon key={f} className="radar-grid"
          points={top.map((_, i) => pointFor(-Math.PI / 2 + i * step, maxRadius * f, cx, cy).join(",")).join(" ")} />
      ))}
      {top.map((_, i) => {
        const [x, y] = pointFor(-Math.PI / 2 + i * step, maxRadius, cx, cy);
        return <line key={i} x1={cx} y1={cy} x2={x} y2={y} className="radar-spoke" />;
      })}
      <polygon points={polygon} className="radar-shape" fill="url(#radar-fill)" />
      {top.map((g, i) => {
        const [px, py] = pts[i];
        const [lx, ly] = pointFor(-Math.PI / 2 + i * step, maxRadius + 18, cx, cy);
        return (
          <g key={g.name}>
            <circle cx={px} cy={py} r={hover === i ? 5 : 3} className="radar-vertex"
              onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
            <text x={lx} y={ly} className="radar-label" textAnchor="middle">
              {hover === i ? `${g.name} ${g.affinity.toFixed(2)}` : g.name}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
