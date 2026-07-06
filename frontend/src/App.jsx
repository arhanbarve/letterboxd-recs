import { useState } from "react";
import RecommendationsPage from "./RecommendationsPage";
import TasteProfilePage from "./TasteProfilePage";

export default function App() {
  const [tab, setTab] = useState("recs");
  return (
    <div>
      <nav>
        <button onClick={() => setTab("recs")}>Recommendations</button>
        <button onClick={() => setTab("taste")}>Taste Profile</button>
      </nav>
      {tab === "recs" ? <RecommendationsPage /> : <TasteProfilePage />}
    </div>
  );
}
