import { useState } from "react";
import RecommendationsPage from "./RecommendationsPage";
import TasteProfilePage from "./TasteProfilePage";
import UsernameField from "./components/UsernameField";
import { useLocalStorage } from "./lib/useLocalStorage";

const TABS = [
  { id: "recs", label: "Recommendations" },
  { id: "taste", label: "Taste Profile" },
];

export default function App() {
  const [tab, setTab] = useState("recs");
  const [username, setUsername] = useLocalStorage("letterboxd_username", "");

  return (
    <div className="app">
      <div className="brand">Letterboxd Recs by Arhan</div>
      <nav className="tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`tab${tab === t.id ? " active" : ""}`}
            onClick={() => setTab(t.id)}
            aria-current={tab === t.id ? "page" : undefined}
          >
            {t.label}
          </button>
        ))}
      </nav>
      <UsernameField value={username} onChange={setUsername} />
      <div className="page" key={tab}>
        {tab === "recs" ? (
          <RecommendationsPage username={username} />
        ) : (
          <TasteProfilePage username={username} />
        )}
      </div>
    </div>
  );
}
