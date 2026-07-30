import { useRef, useState } from "react";
import { importExport } from "../api";

const EXPORT_URL = "https://letterboxd.com/settings/data/";

// Two shapes, one component: the guided panel that teaches the export flow on a
// cold start, and the compact control that sits in the bar once data exists.
export default function ImportPanel({ username, compact = false, onImported }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef(null);

  const submit = async (file) => {
    if (!file || busy) return;
    setBusy(true);
    setError(null);
    try {
      onImported(await importExport(file, username));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";  // allow re-picking the same file
    }
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    submit(e.dataTransfer.files?.[0]);
  };

  const fileInput = (
    <input
      ref={inputRef}
      type="file"
      accept=".zip,application/zip"
      className="import-input"
      aria-label="Letterboxd export zip"
      disabled={busy}
      onChange={(e) => submit(e.target.files?.[0])}
    />
  );

  if (compact) {
    return (
      <span className="import-compact">
        <button
          type="button"
          className="import-btn"
          disabled={busy}
          onClick={() => inputRef.current?.click()}
        >
          {busy ? "Reading…" : "Re-import export"}
        </button>
        {fileInput}
        {error && <span className="import-error" role="alert">{error}</span>}
      </span>
    );
  }

  return (
    <div className="import-panel">
      <h3>Bring in your Letterboxd data</h3>
      <p className="import-lede">
        Letterboxd blocks automated crawling, so you hand us the data yourself. Takes about
        thirty seconds, and you only redo it when you want your new ratings counted.
      </p>
      <ol className="import-steps">
        <li>
          Open <a href={EXPORT_URL} target="_blank" rel="noreferrer">Letterboxd → Settings → Data</a>
        </li>
        <li>Click <strong>Export Your Data</strong> and save the .zip</li>
        <li>Drop it below — nothing leaves your data except the film titles we look up</li>
      </ol>
      <div
        className={`import-drop${dragging ? " dragging" : ""}${busy ? " busy" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <span className="import-drop-label">
          {busy ? "Reading your export…" : "Drop letterboxd-….zip here, or choose a file"}
        </span>
        {fileInput}
      </div>
      {error && <div className="import-error" role="alert">{error}</div>}
    </div>
  );
}
