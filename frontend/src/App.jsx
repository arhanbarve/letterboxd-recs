import { useCallback, useEffect, useState } from "react";
import { NavLink, Routes, Route } from "react-router-dom";
import RecommendationsPage from "./RecommendationsPage";
import TasteProfilePage from "./TasteProfilePage";
import BulbSign from "./components/BulbSign";
import UsernameField from "./components/UsernameField";
import RefreshButton from "./components/RefreshButton";
import ImportPanel from "./components/ImportPanel";
import { getImportStatus } from "./api";
import { useLocalStorage } from "./lib/useLocalStorage";
import { RefreshProvider, useRefresh } from "./context/RefreshContext";

function ControlBar({ username, setUsername, hasImport, onImported }) {
  const { isRunning, cancel, start } = useRefresh();
  return (
    <div className="control-bar">
      <UsernameField value={username} onChange={setUsername} />
      <span className="control-actions">
        {hasImport && <ImportPanel compact username={username} onImported={onImported} />}
        <RefreshButton
          loading={isRunning}
          hasData={hasImport}
          disabled={!hasImport}
          disabledHint="Upload your Letterboxd export first"
          onClick={start}
          onCancel={cancel}
        />
      </span>
    </div>
  );
}

export default function App() {
  const [username, setUsername] = useLocalStorage("letterboxd_username", "");
  const [importStatus, setImportStatus] = useState(null);

  useEffect(() => {
    if (!username) {
      setImportStatus(null);
      return undefined;
    }
    let stale = false;
    getImportStatus(username)
      .then((s) => { if (!stale) setImportStatus(s); })
      .catch(() => { /* an unreachable backend is already surfaced by the page */ });
    return () => { stale = true; };
  }, [username]);

  // profile.csv is authoritative about whose export this is, so importing both
  // stores the data and corrects a mistyped username.
  const onImported = useCallback((result) => {
    const { username: owner, ...status } = result;
    if (owner && owner !== username) setUsername(owner);
    setImportStatus(status);
  }, [username, setUsername]);

  const hasImport = (importStatus?.imported ?? 0) > 0;

  return (
    <div className="app">
      <BulbSign />
      <nav className="tabs">
        <NavLink to="/" end className={({ isActive }) => `tab${isActive ? " active" : ""}`}>Recommendations</NavLink>
        <NavLink to="/taste" className={({ isActive }) => `tab${isActive ? " active" : ""}`}>Taste Profile</NavLink>
      </nav>
      <RefreshProvider username={username}>
        <ControlBar
          username={username}
          setUsername={setUsername}
          hasImport={hasImport}
          onImported={onImported}
        />
        <div className="page">
          <Routes>
            <Route path="/" element={
              <RecommendationsPage
                username={username}
                importStatus={importStatus}
                onImported={onImported}
              />
            } />
            <Route path="/taste" element={<TasteProfilePage username={username} />} />
          </Routes>
        </div>
      </RefreshProvider>
    </div>
  );
}
