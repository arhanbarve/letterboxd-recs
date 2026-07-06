export default function TicketStub({ name, count, maxCount, index = 0 }) {
  const strength = maxCount > 0 ? count / maxCount : 0;
  return (
    <div
      className="ticket-stub"
      style={{
        animationDelay: `${index * 45}ms`,
        borderColor: `color-mix(in srgb, var(--accent) ${Math.round(strength * 70)}%, var(--border))`,
      }}
    >
      <div className="stub-name">{name}</div>
      <div className="stub-count">{count} film{count === 1 ? "" : "s"}</div>
    </div>
  );
}
