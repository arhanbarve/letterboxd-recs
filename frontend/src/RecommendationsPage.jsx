import { useEffect, useRef, useState } from "react";
import { getRecommendations, getRefreshStatus, refresh } from "./api";
import RefreshButton from "./components/RefreshButton";
import RecommendationCard from "./components/RecommendationCard";
import ProgressBar from "./components/ProgressBar";
import WatchProvidersModal from "./components/WatchProvidersModal";

function HeroPoster({ posterPath, title }) {
  const [failed, setFailed] = useState(false);
  if (!posterPath || failed) return null;
  return (
    <div className="hero-poster">
      <img
        src={`https://image.tmdb.org/t/p/w300${posterPath}`}
        alt={title}
        onError={() => setFailed(true)}
      />
    </div>
  );
}

function SkeletonGrid({ count = 6 }) {
  return (
    <div className="grid" aria-hidden="true">
      {Array.from({ length: count }).map((_, i) => (
        <div className="skeleton-card" key={i}>
          <div className="skeleton-block skeleton-poster" />
          <div className="skeleton-block skeleton-line" />
          <div className="skeleton-block skeleton-line short" />
        </div>
      ))}
    </div>
  );
}

export default function RecommendationsPage({ username }) {
  const [recs, setRecs] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [progress, setProgress] = useState(null);
  const [selectedFilm, setSelectedFilm] = useState(null);
  const pollRef = useRef();

  const load = async () => {
    if (!username) return;
    try {
      setRecs(await getRecommendations(username));
    } catch {
      setError("Couldn't load recommendations. Is the backend running?");
    }
  };

  useEffect(() => {
    setRecs(null);
    load();
  }, [username]);

  const onRefresh = async () => {
    if (!username) {
      setError("Enter your Letterboxd username above before refreshing.");
      return;
    }
    setLoading(true);
    setError(null);
    setProgress({ stage: "starting", current: 0, total: null });

    try {
      await refresh(username);
    } catch {
      setError("Couldn't reach the backend to start the refresh. Is it running?");
      setLoading(false);
      setProgress(null);
      return;
    }

    pollRef.current = setInterval(async () => {
      let status;
      try {
        status = await getRefreshStatus(username);
      } catch {
        return; // transient poll failure, keep trying
      }
      setProgress(status);
      if (status.stage === "done") {
        clearInterval(pollRef.current);
        setLoading(false);
        setProgress(null);
        await load();
      } else if (status.stage === "error") {
        clearInterval(pollRef.current);
        setLoading(false);
        setError(`Refresh failed — ${status.message || "check your TMDB key and username, then try again."}`);
      }
    }, 800);
  };

  useEffect(() => () => clearInterval(pollRef.current), []);

  const top = recs && recs.length > 0 ? recs[0] : null;
  const rest = recs && recs.length > 0 ? recs.slice(1) : [];

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <h2 style={{ fontSize: 15, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--muted)", fontFamily: "var(--font-body)" }}>
          Recommendations
        </h2>
        <RefreshButton loading={loading} onClick={onRefresh} />
      </div>

      {loading && <ProgressBar progress={progress} />}

      {error && (
        <div className="error-banner">
          <span className="error-mark">!</span>
          <span>{error}</span>
        </div>
      )}

      {!username && (
        <div className="empty-state">
          <h3>Enter your Letterboxd username</h3>
          <p>Add it above, then click "Refresh my data" to generate recommendations.</p>
        </div>
      )}

      {username && recs === null && <SkeletonGrid />}

      {username && recs !== null && recs.length === 0 && (
        <div className="empty-state">
          <h3>No recommendations yet</h3>
          <p>Click "Refresh my data" to scrape your Letterboxd ratings and generate picks.</p>
        </div>
      )}

      {top && (
        <div
          className="hero-band"
          role="button"
          tabIndex={0}
          onClick={() => setSelectedFilm(top)}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), setSelectedFilm(top))}
          style={{ cursor: "pointer" }}
        >
          <div className="hero-eyebrow">Top Pick Tonight</div>
          <div className="hero-body">
            <HeroPoster key={top.tmdb_id} posterPath={top.poster_path} title={top.title} />
            <div>
              <div className="hero-title">
                {top.title} <span className="hero-meta">({top.year})</span>
              </div>
              <div className="hero-stats">
                <div className="hero-match">
                  {Math.round(top.match_pct)}<span>% match</span>
                </div>
                <div className="hero-predicted">{top.predicted_rating.toFixed(1)}★ predicted</div>
              </div>
              {top.why_tags?.length > 0 && (
                <div className="hero-why">Because you like: {top.why_tags.join(", ")}</div>
              )}
            </div>
          </div>
        </div>
      )}

      {rest.length > 0 && (
        <div className="grid">
          {rest.map((r, i) => (
            <RecommendationCard rec={r} index={i} key={r.tmdb_id} onSelect={setSelectedFilm} />
          ))}
        </div>
      )}

      {selectedFilm && (
        <WatchProvidersModal film={selectedFilm} onClose={() => setSelectedFilm(null)} />
      )}
    </div>
  );
}
