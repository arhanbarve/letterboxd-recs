import { TasteDashboard } from "../TasteProfilePage";
import demo from "./demoData.json";

export default function DemoTastePage() {
  return (
    <div>
      <p className="demo-note">Sample data · @{demo.username}</p>
      <TasteDashboard dash={demo.taste_profile} updatedAt={demo.last_updated} />
    </div>
  );
}
