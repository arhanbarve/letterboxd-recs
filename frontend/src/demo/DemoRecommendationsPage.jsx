import { RecList } from "../RecommendationsPage";
import LastUpdated from "../components/LastUpdated";
import demo from "./demoData.json";

// A frozen snapshot of one real account's output, so the app can be shown
// without an import, an access code, or waiting on the backend to wake up.
export default function DemoRecommendationsPage() {
  return (
    <div>
      <p className="demo-note">Sample data · @{demo.username}</p>
      <LastUpdated iso={demo.last_updated} />
      <RecList recs={demo.recommendations} />
    </div>
  );
}
