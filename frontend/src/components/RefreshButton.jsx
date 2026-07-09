export default function RefreshButton({ loading, hasData, onClick, onCancel }) {
  return (
    <span className="refresh-controls">
      <button
        className={`refresh-btn${loading ? " loading" : ""}`}
        onClick={onClick}
        disabled={loading}
        aria-busy={loading}
      >
        {loading ? "Refreshing…" : hasData ? "Refresh my data" : "Load my data"}
      </button>
      {loading && (
        <button type="button" className="cancel-btn" onClick={onCancel}>
          Cancel
        </button>
      )}
    </span>
  );
}
