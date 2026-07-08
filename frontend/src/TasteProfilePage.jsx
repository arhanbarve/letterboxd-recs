import { useEffect, useState } from "react";
import { getTasteProfile, getLastUpdated } from "./api";
import { useRefresh } from "./context/RefreshContext";
import GenreRadar from "./components/GenreRadar";
import LastUpdated from "./components/LastUpdated";
import ProgressBar from "./components/ProgressBar";

const FACE = "https://image.tmdb.org/t/p/w185";

function StatTile({ value, label }) {
  return (
    <div className="stat-tile">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

function RatingHistogram({ distribution }) {
  const max = Math.max(...distribution.map((b) => b.count), 1);
  return (
    <div className="rating-histogram">
      {distribution.map((b) => (
        <div key={b.star} className="histogram-bar" style={{ height: `${(b.count / max) * 100}%` }}>
          <span>{b.star}★</span>
        </div>
      ))}
    </div>
  );
}

function PeopleWall({ title, people }) {
  if (!people || people.length === 0) return null;
  return (
    <div className="people-wall-section">
      <p className="section-title">{title}</p>
      <div className="people-wall">
        {people.map((p) => (
          <div className="person-face" key={p.name}>
            {p.profile_path ? (
              <img src={FACE + p.profile_path} alt={p.name} />
            ) : (
              <div className="person-face-placeholder">{p.name[0]}</div>
            )}
            <div className="person-name">{p.name}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function AffinityBars({ genres }) {
  const top = genres.slice(0, 6);
  const max = Math.max(...top.map((g) => Math.abs(g.affinity)), 0.01);
  return (
    <div className="affinity-bars">
      {top.map((g) => (
        <div className="affinity-row" key={g.name}>
          <span className="affinity-name">{g.name}</span>
          <span className="affinity-track">
            <span className="affinity-fill" style={{ width: `${(Math.max(g.affinity, 0) / max) * 100}%` }} />
          </span>
        </div>
      ))}
    </div>
  );
}

export default function TasteProfilePage({ username }) {
  const [dash, setDash] = useState(null);
  const [updatedAt, setUpdatedAt] = useState(null);
  const { status, isRunning, lastCompletedAt } = useRefresh();

  const load = () => {
    if (!username) return;
    getTasteProfile(username).then(setDash);
    getLastUpdated(username).then((r) => setUpdatedAt(r.last_updated)).catch(() => {});
  };

  useEffect(() => {
    if (!username) return;
    setDash(null);
    setUpdatedAt(null);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [username]);

  useEffect(() => {
    if (lastCompletedAt) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastCompletedAt]);

  if (!username) {
    return (
      <div className="empty-state">
        <h3>Enter your Letterboxd username</h3>
        <p>Add it above to see your taste profile.</p>
      </div>
    );
  }

  if (dash === null) {
    return isRunning ? <ProgressBar status={status} /> : null;
  }

  if (dash.total_rated === 0) {
    return (
      <div>
        {isRunning && <ProgressBar status={status} />}
        <div className="empty-state">
          <h3>No taste profile yet</h3>
          <p>Refresh your data from the Recommendations tab to build your taste profile.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="taste-dashboard">
      {isRunning && <ProgressBar status={status} />}
      <div className="dashboard-eyebrow-row">
        <div className="dashboard-eyebrow">Your Taste Fingerprint</div>
        <LastUpdated iso={updatedAt} />
      </div>

      <div className="stat-row">
        <StatTile value={dash.total_rated} label="Films rated" />
        <StatTile value={dash.average_rating.toFixed(1) + "★"} label="Avg you give" />
        <StatTile value={dash.favorite_decade ? `${dash.favorite_decade}s` : "—"} label="Favorite decade" />
        <StatTile value={dash.top_directors[0]?.name ?? "—"} label="Top director" />
      </div>

      <div className="dashboard-grid">
        <div>
          <p className="section-title">How you rate</p>
          <RatingHistogram distribution={dash.rating_distribution} />
          <div className="signature-line">{dash.signature}</div>
        </div>
        <div>
          <p className="section-title">Strongest affinities</p>
          <AffinityBars genres={dash.genre_affinities} />
          {dash.top_keywords.length > 0 && (
            <div className="keyword-chips">
              {dash.top_keywords.map((k) => (
                <span className="keyword-chip" key={k}>{k}</span>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="dashboard-grid">
        <div>
          <p className="section-title">Genre radar</p>
          <GenreRadar genres={dash.genre_affinities} />
        </div>
        <div>
          <PeopleWall title="Top directors" people={dash.top_directors} />
          <PeopleWall title="Top actors" people={dash.top_actors} />
        </div>
      </div>
    </div>
  );
}
