const BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

export async function getRecommendations(username) {
  const r = await fetch(`${BASE}/api/recommendations?username=${encodeURIComponent(username)}`);
  return r.json();
}

export async function getTasteProfile(username) {
  const r = await fetch(`${BASE}/api/taste-profile?username=${encodeURIComponent(username)}`);
  return r.json();
}

export async function refresh(username) {
  const r = await fetch(`${BASE}/api/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username }),
  });
  return r.json();
}

export async function getRefreshStatus(username) {
  const r = await fetch(`${BASE}/api/refresh/status?username=${encodeURIComponent(username)}`);
  return r.json();
}

export async function getWatchProviders(tmdbId) {
  const r = await fetch(`${BASE}/api/films/${tmdbId}/watch-providers`);
  return r.json();
}
