import { useEffect, useState } from "react";
import { getTasteProfile } from "./api";
import TicketStub from "./components/TicketStub";

function StubSection({ title, items }) {
  if (!items || items.length === 0) return null;
  const maxCount = Math.max(...items.map((i) => i.count));
  return (
    <div className="taste-section">
      <h2>{title}</h2>
      <div className="stub-grid">
        {items.map((i, idx) => (
          <TicketStub key={i.name} name={i.name} count={i.count} maxCount={maxCount} index={idx} />
        ))}
      </div>
    </div>
  );
}

export default function TasteProfilePage({ username }) {
  const [profile, setProfile] = useState(null);

  useEffect(() => {
    if (!username) return;
    setProfile(null);
    getTasteProfile(username).then(setProfile);
  }, [username]);

  if (!username) {
    return (
      <div className="empty-state">
        <h3>Enter your Letterboxd username</h3>
        <p>Add it above to see your taste profile.</p>
      </div>
    );
  }

  const genres = profile?.genres ?? [];
  const actors = profile?.actors ?? [];

  if (profile && genres.length === 0 && actors.length === 0) {
    return (
      <div className="empty-state">
        <h3>No taste profile yet</h3>
        <p>Refresh your data from the Recommendations tab to build your taste profile.</p>
      </div>
    );
  }

  return (
    <div>
      <StubSection title="Top Genres" items={genres} />
      <StubSection title="Top Actors" items={actors} />
    </div>
  );
}
