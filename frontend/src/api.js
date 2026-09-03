import { getAccessCode, setAccessCode } from "./lib/accessCode";

const BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

// Every user-scoped endpoint is gated on the access code minted at first import,
// so a stranger who guesses a Letterboxd username still gets a 403.
function authHeaders(username, extra) {
  const code = getAccessCode(username);
  return { ...extra, ...(code ? { "X-Access-Code": code } : {}) };
}

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `Request failed (${status})`);
    this.status = status;
  }
}

async function getJson(path, username) {
  const r = await fetch(`${BASE}${path}`, { headers: authHeaders(username) });
  const body = await r.json().catch(() => ({}));
  // Endpoints are gated on the access code now, so a response is no longer
  // guaranteed to have the shape the caller expects — a 403 body is an error
  // object. Throw rather than hand a caller something it will destructure.
  if (!r.ok) throw new ApiError(r.status, body.detail);
  return body;
}

export async function getRecommendations(username) {
  return getJson(`/api/recommendations?username=${encodeURIComponent(username)}`, username);
}

export async function importExport(file, username) {
  const form = new FormData();
  form.append("file", file);
  if (username) form.append("username", username);
  const r = await fetch(`${BASE}/api/import`, {
    method: "POST",
    body: form,
    // A re-import has to prove it owns the username it is overwriting.
    headers: authHeaders(username),
  });
  const body = await r.json().catch(() => ({}));
  // The backend's 400s and 403s are written to be shown as-is ("No ratings.csv
  // inside that zip...") — surface them rather than a generic failure.
  if (!r.ok) throw new Error(body.detail || "Couldn't read that file. Try again.");
  // profile.csv is authoritative about the owner, so store the code under the
  // name the backend settled on, not the one that was typed.
  if (body.access_code) setAccessCode(body.username, body.access_code);
  return body;
}

export async function getImportStatus(username) {
  return getJson(`/api/import/status?username=${encodeURIComponent(username)}`, username);
}

export async function getTasteProfile(username) {
  return getJson(`/api/taste-profile?username=${encodeURIComponent(username)}`, username);
}

export async function getLastUpdated(username) {
  return getJson(`/api/last-updated?username=${encodeURIComponent(username)}`, username);
}

export async function refresh(username) {
  const r = await fetch(`${BASE}/api/refresh`, {
    method: "POST",
    headers: authHeaders(username, { "Content-Type": "application/json" }),
    body: JSON.stringify({ username }),
  });
  return r.json();
}

export async function getRefreshStatus(username) {
  return getJson(`/api/refresh/status?username=${encodeURIComponent(username)}`, username);
}

export async function cancelRefresh(username) {
  const r = await fetch(`${BASE}/api/refresh/cancel`, {
    method: "POST",
    headers: authHeaders(username, { "Content-Type": "application/json" }),
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
