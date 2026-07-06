import { useRef, useState } from "react";

export default function UsernameField({ value, onChange }) {
  const [draft, setDraft] = useState(value);
  const [saved, setSaved] = useState(false);
  const timeoutRef = useRef();

  const commit = () => {
    const trimmed = draft.trim();
    if (trimmed === value) return;
    onChange(trimmed);
    setSaved(true);
    clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => setSaved(false), 1400);
  };

  return (
    <div className="username-field">
      <label htmlFor="letterboxd-username">Letterboxd username</label>
      <input
        id="letterboxd-username"
        type="text"
        value={draft}
        placeholder="e.g. davidfincher"
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
      />
      <span className={`saved-indicator${saved ? " visible" : ""}`} aria-live="polite">
        {saved ? "Saved" : ""}
      </span>
    </div>
  );
}
