import { useEffect, useState } from "react";
import { getWatchProviders } from "../api";

const LOGO = "https://image.tmdb.org/t/p/w45";

function ProviderRow({ label, providers }) {
  if (!providers || providers.length === 0) return null;
  return (
    <div className="provider-row">
      <div className="provider-label">{label}</div>
      <div className="provider-logos">
        {providers.map((p) => (
          <img key={p.name} src={LOGO + p.logo_path} alt={p.name} title={p.name} />
        ))}
      </div>
    </div>
  );
}

export default function WatchProvidersModal({ film, onClose }) {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setData(null);
    setFailed(false);
    getWatchProviders(film.tmdb_id)
      .then(setData)
      .catch(() => setFailed(true));
  }, [film.tmdb_id]);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const hasAny = data && (data.flatrate.length || data.rent.length || data.buy.length);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={`Where to watch ${film.title}`}
        onClick={(e) => e.stopPropagation()}
      >
        <button className="modal-close" onClick={onClose} aria-label="Close">
          ×
        </button>
        <h3>{film.title} ({film.year})</h3>
        <p className="modal-subtitle">Where to watch</p>

        {data === null && !failed && <p className="modal-loading">Loading...</p>}
        {failed && <p className="modal-loading">Couldn't load streaming info.</p>}
        {data && !hasAny && <p className="modal-loading">Not currently available to stream, rent, or buy (US).</p>}

        {data && hasAny && (
          <>
            <ProviderRow label="Stream" providers={data.flatrate} />
            <ProviderRow label="Rent" providers={data.rent} />
            <ProviderRow label="Buy" providers={data.buy} />
          </>
        )}

        {data?.link && (
          <a className="modal-link" href={data.link} target="_blank" rel="noreferrer">
            View all options →
          </a>
        )}
        <p className="modal-attribution">Streaming data via JustWatch</p>
      </div>
    </div>
  );
}
