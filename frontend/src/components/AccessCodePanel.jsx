import { useState } from "react";
import { getImportStatus } from "../api";
import { setAccessCode } from "../lib/accessCode";

// Two shapes, one component — mirroring ImportPanel. "issued" shows the code the
// backend just minted, which is the only time it is ever visible in full;
// "locked" is what a second device sees, where the username is already claimed
// but this browser holds no code.
export default function AccessCodePanel({ username, issuedCode, onUnlocked }) {
  const [draft, setDraft] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(issuedCode);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      setError("Couldn't copy — select the code and copy it manually.");
    }
  };

  const unlock = async (e) => {
    e.preventDefault();
    const code = draft.trim();
    if (!code || busy) return;
    setBusy(true);
    setError(null);
    // Store first, then probe: getImportStatus reads the code back out of
    // storage, and a wrong one comes back as claimed-but-empty.
    setAccessCode(username, code);
    try {
      const status = await getImportStatus(username);
      if ((status.imported ?? 0) > 0) {
        onUnlocked(status);
      } else {
        setError("That code doesn't match this username.");
      }
    } catch {
      setError("Couldn't reach the backend. Try again.");
    } finally {
      setBusy(false);
    }
  };

  if (issuedCode) {
    return (
      <div className="access-panel issued">
        <h3>Save your access code</h3>
        <p className="access-lede">
          This code is what keeps <strong>{username}</strong>'s ratings private — anyone
          without it gets turned away. It is shown once. Save it if you ever want to open
          your recommendations on another device.
        </p>
        <div className="access-code-row">
          <code className="access-code">{issuedCode}</code>
          <button type="button" className="import-btn" onClick={copy}>
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
        {error && <div className="import-error" role="alert">{error}</div>}
      </div>
    );
  }

  return (
    <div className="access-panel">
      <h3>That username is already taken</h3>
      <p className="access-lede">
        Someone has already imported an export as <strong>{username}</strong>. If that was
        you, paste the access code you were given. If it wasn't, use your own Letterboxd
        username instead.
      </p>
      <form className="access-form" onSubmit={unlock}>
        <label htmlFor="access-code-input">Access code</label>
        <input
          id="access-code-input"
          type="text"
          autoComplete="off"
          spellCheck="false"
          value={draft}
          placeholder="paste your code"
          onChange={(e) => setDraft(e.target.value)}
        />
        <button type="submit" className="import-btn" disabled={busy || !draft.trim()}>
          {busy ? "Checking…" : "Unlock"}
        </button>
      </form>
      {error && <div className="import-error" role="alert">{error}</div>}
    </div>
  );
}
