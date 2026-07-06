const BASE = "http://127.0.0.1:8000";

export async function getRecommendations() {
  const r = await fetch(`${BASE}/api/recommendations`);
  return r.json();
}

export async function getTasteProfile() {
  const r = await fetch(`${BASE}/api/taste-profile`);
  return r.json();
}

export async function refresh(username) {
  const r = await fetch(`${BASE}/api/refresh`, {
    method: "POST",
    headers: username ? { "Content-Type": "application/json" } : undefined,
    body: username ? JSON.stringify({ username }) : undefined,
  });
  return r.json();
}

export async function getRefreshStatus() {
  const r = await fetch(`${BASE}/api/refresh/status`);
  return r.json();
}

export async function getWatchProviders(tmdbId) {
  const r = await fetch(`${BASE}/api/films/${tmdbId}/watch-providers`);
  return r.json();
}
