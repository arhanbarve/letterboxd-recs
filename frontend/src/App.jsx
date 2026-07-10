import { NavLink, Routes, Route } from "react-router-dom";
import RecommendationsPage from "./RecommendationsPage";
import TasteProfilePage from "./TasteProfilePage";
import BulbSign from "./components/BulbSign";
import UsernameField from "./components/UsernameField";
import RefreshButton from "./components/RefreshButton";
import { useLocalStorage } from "./lib/useLocalStorage";
import { RefreshProvider, useRefresh } from "./context/RefreshContext";

function ControlBar({ username, setUsername }) {
  const { isRunning, cancel, start } = useRefresh();
  return (
    <div className="control-bar">
      <UsernameField value={username} onChange={setUsername} />
      <RefreshButton loading={isRunning} hasData onClick={start} onCancel={cancel} />
    </div>
  );
}

export default function App() {
  const [username, setUsername] = useLocalStorage("letterboxd_username", "");
  return (
    <div className="app">
      <BulbSign />
      <nav className="tabs">
        <NavLink to="/" end className={({ isActive }) => `tab${isActive ? " active" : ""}`}>Recommendations</NavLink>
        <NavLink to="/taste" className={({ isActive }) => `tab${isActive ? " active" : ""}`}>Taste Profile</NavLink>
      </nav>
      <RefreshProvider username={username}>
        <ControlBar username={username} setUsername={setUsername} />
        <div className="page">
          <Routes>
            <Route path="/" element={<RecommendationsPage username={username} />} />
            <Route path="/taste" element={<TasteProfilePage username={username} />} />
          </Routes>
        </div>
      </RefreshProvider>
    </div>
  );
}
