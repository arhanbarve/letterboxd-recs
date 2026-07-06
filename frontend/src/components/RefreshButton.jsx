export default function RefreshButton({ loading, onClick }) {
  return (
    <button
      className={`refresh-btn${loading ? " loading" : ""}`}
      onClick={onClick}
      disabled={loading}
      aria-busy={loading}
    >
      {loading ? "Refreshing…" : "Refresh my data"}
    </button>
  );
}
