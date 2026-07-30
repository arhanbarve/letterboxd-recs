export default function RefreshButton({ loading, hasData, disabled, disabledHint, onClick, onCancel }) {
  return (
    <span className="refresh-controls">
      <button
        className={`refresh-btn${loading ? " loading" : ""}`}
        onClick={onClick}
        disabled={loading || disabled}
        title={disabled && !loading ? disabledHint : undefined}
        aria-busy={loading}
      >
        {loading ? "Refreshing…" : hasData ? "Refresh recommendations" : "Generate recommendations"}
      </button>
      {loading && (
        <button type="button" className="cancel-btn" onClick={onCancel}>
          Cancel
        </button>
      )}
    </span>
  );
}
