import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { getFilmDetail, getWatchProviders } from "../api";
import { ratingBadge } from "../lib/ratingBadge";

const BACKDROP = "https://image.tmdb.org/t/p/w780";
const LOGO = "https://image.tmdb.org/t/p/w45";

function ProviderRow({ label, providers }) {
  if (!providers || providers.length === 0) return null;
  return (
    <div className="provider-row">
      <div className="provider-label">{label}</div>
      <div className="provider-logos">
        {providers.map((p) => <img key={p.name} src={LOGO + p.logo_path} alt={p.name} title={p.name} />)}
      </div>
    </div>
  );
}

export default function ExpandedFilmCard({ film, onClose }) {
  const [detail, setDetail] = useState(null);
  const [providers, setProviders] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setDetail(null); setProviders(null); setFailed(false);
    getFilmDetail(film.tmdb_id).then(setDetail).catch(() => {});
    getWatchProviders(film.tmdb_id).then(setProviders).catch(() => setFailed(true));
  }, [film.tmdb_id]);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";  // lock background scroll while open
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [onClose]);

  const badge = ratingBadge({ ...film, ...(detail || {}) });
  const hasProviders = providers && (providers.flatrate.length || providers.rent.length || providers.buy.length);

  return createPortal(
    <div className="expand-backdrop" onClick={onClose}>
      <div className="expand-card" role="dialog" aria-modal="true" aria-label={`${film.title} details`}
           onClick={(e) => e.stopPropagation()}>
        <button className="expand-close" onClick={onClose} aria-label="Close">×</button>
        {(detail?.backdrop_path || film.backdrop_path) && (
          <div className="expand-hero" style={{ backgroundImage: `url(${BACKDROP}${detail?.backdrop_path || film.backdrop_path})` }} />
        )}
        <div className="expand-body">
          <h3 className="expand-title">{film.title} <span>({film.year})</span></h3>
          {film.starring?.length > 0 && <p className="expand-starring">Starring {film.starring.join(", ")}</p>}
          <div className="expand-stats">
            <span className="expand-match">{Math.round(film.match_pct)}% match</span>
            <span>{film.predicted_rating?.toFixed(1)}★ predicted</span>
            {badge && <span className="expand-rating">{badge.label} {badge.value}</span>}
            {film.rt_score != null && <span className="expand-rating">RT {film.rt_score}%</span>}
          </div>
          {film.why?.neighbors?.length > 0 && (
            <p className="expand-why">
              Because you loved{" "}
              {film.why.neighbors.map((n, i) => (
                <span key={n.title}>{i > 0 && " and "}<b>{n.title}</b> ({n.rating}★)</span>
              ))}
              {film.why.connection ? ` — ${film.why.connection}.` : "."}
            </p>
          )}
          {detail?.runtime && <p className="expand-meta">{detail.runtime} min · {detail.director}</p>}
          {detail?.overview && <p className="expand-overview">{detail.overview}</p>}
          {detail?.genres?.length > 0 && <p className="expand-genres">{detail.genres.join(" · ")}</p>}
          <p className="section-title" style={{ marginTop: 18 }}>Where to watch</p>
          {providers === null && !failed && <p className="modal-loading">Loading…</p>}
          {failed && <p className="modal-loading">Couldn't load streaming info.</p>}
          {providers && !hasProviders && <p className="modal-loading">Not currently available to stream, rent, or buy (US).</p>}
          {providers && hasProviders && (
            <>
              <ProviderRow label="Stream" providers={providers.flatrate} />
              <ProviderRow label="Rent" providers={providers.rent} />
              <ProviderRow label="Buy" providers={providers.buy} />
            </>
          )}
          {providers?.link && <a className="modal-link" href={providers.link} target="_blank" rel="noreferrer">View all options →</a>}
        </div>
      </div>
    </div>,
    document.body,
  );
}
