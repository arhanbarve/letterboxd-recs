import { useEffect, useRef, useState } from "react";
import { getRecommendations, getRefreshStatus, getLastUpdated, refresh } from "./api";
import RefreshButton from "./components/RefreshButton";
import RecommendationCard from "./components/RecommendationCard";
import ProgressBar from "./components/ProgressBar";
import MarqueeTrio from "./components/MarqueeTrio";
import FilmDetailModal from "./components/FilmDetailModal";
import LastUpdated from "./components/LastUpdated";

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
  const [updatedAt, setUpdatedAt] = useState(null);
  const pollRef = useRef();

  const load = async () => {
    if (!username) return;
    try {
      setRecs(await getRecommendations(username));
    } catch {
      setError("Couldn't load recommendations. Is the backend running?");
    }
    try {
      setUpdatedAt((await getLastUpdated(username)).last_updated);
    } catch {
      // non-critical, skip silently
    }
  };

  useEffect(() => {
    setRecs(null);
    setUpdatedAt(null);
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

  const LONG_SHOT_THRESHOLD = 70;
  const PAGE_SIZE = 25;

  const trio = recs ? recs.slice(0, 3) : [];
  const remaining = recs ? recs.slice(3) : [];
  const mainList = remaining.filter((r) => r.match_pct >= LONG_SHOT_THRESHOLD);
  const longShots = remaining.filter((r) => r.match_pct < LONG_SHOT_THRESHOLD);
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const visibleMain = mainList.slice(0, visibleCount);
  const [showLongShots, setShowLongShots] = useState(false);

  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
    setShowLongShots(false);
  }, [recs]);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <h2 style={{ fontSize: 15, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--muted)", fontFamily: "var(--font-body)" }}>
          Recommendations
        </h2>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <LastUpdated iso={updatedAt} />
          <RefreshButton loading={loading} onClick={onRefresh} />
        </div>
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

      <MarqueeTrio recs={trio} onSelect={setSelectedFilm} />

      {visibleMain.length > 0 && (
        <div className="grid">
          {visibleMain.map((r, i) => (
            <RecommendationCard rec={r} index={i} key={r.tmdb_id} onSelect={setSelectedFilm} />
          ))}
        </div>
      )}

      {visibleCount < mainList.length && (
        <button className="show-more-button" onClick={() => setVisibleCount((c) => c + PAGE_SIZE)}>
          Show {Math.min(PAGE_SIZE, mainList.length - visibleCount)} more
        </button>
      )}

      {longShots.length > 0 && (
        <div className="long-shots-section">
          <button className="long-shots-toggle" onClick={() => setShowLongShots((s) => !s)}>
            {showLongShots ? "Hide" : "Show"} long shots ({longShots.length} below {LONG_SHOT_THRESHOLD}% match)
          </button>
          {showLongShots && (
            <div className="grid">
              {longShots.map((r, i) => (
                <RecommendationCard rec={r} index={i} key={r.tmdb_id} onSelect={setSelectedFilm} />
              ))}
            </div>
          )}
        </div>
      )}

      {selectedFilm && (
        <FilmDetailModal film={selectedFilm} onClose={() => setSelectedFilm(null)} />
      )}
    </div>
  );
}
