const BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

export async function getRecommendations(username) {
  const r = await fetch(`${BASE}/api/recommendations?username=${encodeURIComponent(username)}`);
  return r.json();
}

export async function importExport(file, username) {
  const form = new FormData();
  form.append("file", file);
  if (username) form.append("username", username);
  const r = await fetch(`${BASE}/api/import`, { method: "POST", body: form });
  const body = await r.json().catch(() => ({}));
  // The backend's 400s are written to be shown as-is ("No ratings.csv inside
  // that zip...") — surface them rather than a generic failure.
  if (!r.ok) throw new Error(body.detail || "Couldn't read that file. Try again.");
  return body;
}

export async function getImportStatus(username) {
  const r = await fetch(`${BASE}/api/import/status?username=${encodeURIComponent(username)}`);
  return r.json();
}

export async function getTasteProfile(username) {
  const r = await fetch(`${BASE}/api/taste-profile?username=${encodeURIComponent(username)}`);
  return r.json();
}

export async function getLastUpdated(username) {
  const r = await fetch(`${BASE}/api/last-updated?username=${encodeURIComponent(username)}`);
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

export async function cancelRefresh(username) {
  const r = await fetch(`${BASE}/api/refresh/cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username }),
  });
  return r.json();
}

export async function getWatchProviders(tmdbId) {
  const r = await fetch(`${BASE}/api/films/${tmdbId}/watch-providers`);
  return r.json();
}

export async function getFilmDetail(tmdbId) {
  const r = await fetch(`${BASE}/api/films/${tmdbId}`);
  return r.json();
}
