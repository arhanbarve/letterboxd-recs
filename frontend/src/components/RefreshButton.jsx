import { useRef } from "react";

export default function RefreshButton({ loading, hasData, onClick, onCancel, onImport }) {
  const fileRef = useRef(null);
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
      {!loading && onImport && (
        <>
          <button
            type="button"
            className="import-link"
            title="Blocked by Letterboxd? Export your data (Settings → Data → Export) and import the zip here."
            onClick={() => fileRef.current?.click()}
          >
            Import from Letterboxd export
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".zip,.csv"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onImport(f);
              e.target.value = "";
            }}
          />
        </>
      )}
    </span>
  );
}
