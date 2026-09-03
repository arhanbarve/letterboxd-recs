// The backend mints one access code per Letterboxd username on first import.
// It is the only thing standing between someone's taste profile and anyone who
// can guess their username, so it is kept per-username rather than globally —
// two people sharing a browser must not inherit each other's access.

const key = (username) => `reel_access_code:${username}`;

export function getAccessCode(username) {
  if (!username) return null;
  try {
    return window.localStorage.getItem(key(username));
  } catch {
    return null; // private-mode browsers throw rather than return null
  }
}

export function setAccessCode(username, code) {
  if (!username || !code) return;
  try {
    window.localStorage.setItem(key(username), code);
  } catch {
    /* the code is still usable for this session; nothing to recover here */
  }
}

export function clearAccessCode(username) {
  if (!username) return;
  try {
    window.localStorage.removeItem(key(username));
  } catch {
    /* nothing to do */
  }
}
