const BASE = "http://127.0.0.1:8000";

export async function getRecommendations() {
  const r = await fetch(`${BASE}/api/recommendations`);
  return r.json();
}

export async function getTasteProfile() {
  const r = await fetch(`${BASE}/api/taste-profile`);
  return r.json();
}

export async function refresh() {
  const r = await fetch(`${BASE}/api/refresh`, { method: "POST" });
  return r.json();
}
