import { useEffect, useState } from "react";
import { getFilmDetail, getWatchProviders } from "../api";

const BACKDROP = "https://image.tmdb.org/t/p/w780";
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

export default function FilmDetailModal({ film, onClose }) {
  const [detail, setDetail] = useState(null);
  const [providers, setProviders] = useState(null);
  const [providersFailed, setProvidersFailed] = useState(false);

  useEffect(() => {
    setDetail(null);
    setProviders(null);
    setProvidersFailed(false);
    getFilmDetail(film.tmdb_id).then(setDetail).catch(() => {});
    getWatchProviders(film.tmdb_id).then(setProviders).catch(() => setProvidersFailed(true));
  }, [film.tmdb_id]);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const hasProviders = providers && (providers.flatrate.length || providers.rent.length || providers.buy.length);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal film-detail-modal"
        role="dialog"
        aria-modal="true"
        aria-label={`${film.title} details`}
        onClick={(e) => e.stopPropagation()}
      >
        <button className="modal-close" onClick={onClose} aria-label="Close">
          ×
        </button>

        {detail?.backdrop_path && (
          <div className="modal-backdrop-image" style={{ backgroundImage: `url(${BACKDROP}${detail.backdrop_path})` }} />
        )}

        <h3>{film.title} ({film.year})</h3>
        {detail?.runtime && <p className="modal-meta">{detail.runtime} min · {detail.director}</p>}

        {film.why?.neighbors?.length > 0 && (
          <p className="modal-why">
            Because you loved{" "}
            {film.why.neighbors.map((n, i) => (
              <span key={n.title}>
                {i > 0 && " and "}
                <b>{n.title}</b> ({n.rating}★)
              </span>
            ))}
            {film.why.connection ? ` — ${film.why.connection}.` : "."}
          </p>
        )}

        <div className="modal-stats">
          <span>{Math.round(film.match_pct)}% match</span>
          <span>{film.predicted_rating?.toFixed(1)}★ predicted</span>
        </div>

        {detail?.overview && <p className="modal-overview">{detail.overview}</p>}
        {detail?.genres?.length > 0 && <p className="modal-genres">{detail.genres.join(" · ")}</p>}
        {detail?.cast?.length > 0 && <p className="modal-cast">Starring {detail.cast.join(", ")}</p>}

        <p className="modal-subtitle">Where to watch</p>
        {providers === null && !providersFailed && <p className="modal-loading">Loading...</p>}
        {providersFailed && <p className="modal-loading">Couldn't load streaming info.</p>}
        {providers && !hasProviders && <p className="modal-loading">Not currently available to stream, rent, or buy (US).</p>}
        {providers && hasProviders && (
          <>
            <ProviderRow label="Stream" providers={providers.flatrate} />
            <ProviderRow label="Rent" providers={providers.rent} />
            <ProviderRow label="Buy" providers={providers.buy} />
          </>
        )}
        {providers?.link && (
          <a className="modal-link" href={providers.link} target="_blank" rel="noreferrer">
            View all options →
          </a>
        )}
        <p className="modal-attribution">Streaming data via JustWatch</p>
      </div>
    </div>
  );
}
