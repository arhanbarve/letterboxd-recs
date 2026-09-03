import { useEffect, useRef, useState } from "react";
import { getRecommendations, getLastUpdated } from "./api";
import { useRefresh } from "./context/RefreshContext";
import { partitionRecs } from "./lib/recList";
import RecommendationCard from "./components/RecommendationCard";
import ProgressBar from "./components/ProgressBar";
import MarqueeTrio from "./components/MarqueeTrio";
import ExpandedFilmCard from "./components/ExpandedFilmCard";
import LastUpdated from "./components/LastUpdated";
import ImportPanel from "./components/ImportPanel";
import AccessCodePanel from "./components/AccessCodePanel";

const LONG_SHOT_PAGE = 50;

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

export default function RecommendationsPage({
  username, importStatus, onImported, issuedCode, needsCode, onUnlocked,
}) {
  const [recs, setRecs] = useState(null);
  const [error, setError] = useState(null);
  const [selectedFilm, setSelectedFilm] = useState(null);
  const [updatedAt, setUpdatedAt] = useState(null);
  const { status, isRunning, lastCompletedAt } = useRefresh();
  const hasImport = (importStatus?.imported ?? 0) > 0;

  const load = async () => {
    // These endpoints need the access code, and without an import there is
    // nothing to fetch anyway — asking would only produce a 403 to swallow.
    if (!username || !hasImport) return;
    try {
      setRecs(await getRecommendations(username));
    } catch (e) {
      setError(e.status === 403
        ? "That access code doesn't unlock this username's recommendations."
        : "Couldn't load recommendations. Is the backend running?");
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
    setError(null);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [username, hasImport]);

  const lastCompletedAtRef = useRef(lastCompletedAt);
  useEffect(() => {
    if (lastCompletedAt && lastCompletedAt !== lastCompletedAtRef.current) {
      load();
    }
    lastCompletedAtRef.current = lastCompletedAt;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastCompletedAt]);

  useEffect(() => {
    if (status?.stage === "error") {
      setError(`Refresh failed — ${status.message || "check your TMDB key and username, then try again."}`);
    }
  }, [status]);

  const { hero, main, longShots } = recs ? partitionRecs(recs) : { hero: [], main: [], longShots: [] };
  const [longShown, setLongShown] = useState(0); // start collapsed
  useEffect(() => { setLongShown(0); }, [recs]);

  return (
    <div>
      <LastUpdated iso={updatedAt} />

      {isRunning && <ProgressBar />}

      {error && (
        <div className="error-banner">
          <span className="error-mark">!</span>
          <span>{error}</span>
        </div>
      )}

      {issuedCode && (
        <AccessCodePanel username={username} issuedCode={issuedCode} />
      )}

      {needsCode && (
        <AccessCodePanel username={username} onUnlocked={onUnlocked} />
      )}

      {!hasImport && !needsCode && <ImportPanel username={username} onImported={onImported} />}

      {hasImport && recs === null && <SkeletonGrid />}

      {hasImport && recs !== null && recs.length === 0 && !isRunning && (
        <div className="empty-state">
          <h3>No recommendations yet</h3>
          <p>
            {importStatus.imported} films imported. Click "Generate recommendations" to
            score them and build your picks.
          </p>
        </div>
      )}

      <MarqueeTrio recs={hero} onSelect={setSelectedFilm} />

      {main.length > 0 && (
        <div className="grid">
          {main.map((r, i) => (
            <RecommendationCard rec={r} index={i} key={r.tmdb_id} onSelect={setSelectedFilm} />
          ))}
        </div>
      )}

      {longShots.length > 0 && (
        <div className="long-shots-section">
          {longShown === 0 ? (
            <button className="long-shots-toggle" onClick={() => setLongShown(LONG_SHOT_PAGE)}>
              Load long shots ({longShots.length})
            </button>
          ) : (
            <>
              <div className="grid">
                {longShots.slice(0, longShown).map((r, i) => (
                  <RecommendationCard rec={r} index={i} key={r.tmdb_id} onSelect={setSelectedFilm} />
                ))}
              </div>
              {longShown < longShots.length && (
                <button className="long-shots-toggle" onClick={() => setLongShown((n) => n + LONG_SHOT_PAGE)}>
                  Load 50 more
                </button>
              )}
            </>
          )}
        </div>
      )}

      {selectedFilm && <ExpandedFilmCard film={selectedFilm} onClose={() => setSelectedFilm(null)} />}
    </div>
  );
}
