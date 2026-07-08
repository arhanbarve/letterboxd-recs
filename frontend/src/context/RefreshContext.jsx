import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { refresh, getRefreshStatus, cancelRefresh } from "../api";

const ACTIVE_STAGES = new Set(["starting", "scraping", "enriching", "profiling", "scoring"]);
const POLL_MS = 800;

const RefreshContext = createContext(null);

export function RefreshProvider({ username, children }) {
  const [status, setStatus] = useState(null);
  const [lastCompletedAt, setLastCompletedAt] = useState(null);
  const pollRef = useRef(null);
  const prevStageRef = useRef(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const applyStatus = useCallback((s) => {
    setStatus(s);
    if (s.stage === "done" && prevStageRef.current !== "done") {
      setLastCompletedAt(Date.now());
    }
    prevStageRef.current = s.stage;
    if (!ACTIVE_STAGES.has(s.stage)) {
      stopPolling();
    }
  }, [stopPolling]);

  const startPolling = useCallback((user) => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      let s;
      try {
        s = await getRefreshStatus(user);
      } catch {
        return; // transient poll failure, keep trying
      }
      applyStatus(s);
    }, POLL_MS);
  }, [applyStatus, stopPolling]);

  useEffect(() => {
    stopPolling();
    setStatus(null);
    prevStageRef.current = null;
    if (!username) return undefined;

    let cancelled = false;
    (async () => {
      let s;
      try {
        s = await getRefreshStatus(username);
      } catch {
        return;
      }
      if (cancelled) return;
      applyStatus(s);
      if (ACTIVE_STAGES.has(s.stage)) {
        startPolling(username);
      }
    })();

    return () => {
      cancelled = true;
      stopPolling();
    };
  }, [username, applyStatus, startPolling, stopPolling]);

  const start = useCallback(async () => {
    if (!username) return { status: "no_username" };
    applyStatus({ stage: "starting", current: 0, total: null, message: "Starting refresh..." });
    let res;
    try {
      res = await refresh(username);
    } catch {
      applyStatus({ stage: "error", current: 0, total: null, message: "Couldn't reach the backend to start the refresh. Is it running?" });
      return { status: "error" };
    }
    startPolling(username); // rejoin the run whether we started it or it was already_running
    return res;
  }, [username, applyStatus, startPolling]);

  const cancel = useCallback(async () => {
    if (!username) return;
    try {
      await cancelRefresh(username);
    } catch {
      // ignore — the next poll reflects true backend state either way
    }
  }, [username]);

  const isRunning = !!status && ACTIVE_STAGES.has(status.stage);

  return (
    <RefreshContext.Provider value={{ status, isRunning, start, cancel, lastCompletedAt }}>
      {children}
    </RefreshContext.Provider>
  );
}

export function useRefresh() {
  const ctx = useContext(RefreshContext);
  if (!ctx) throw new Error("useRefresh must be used within RefreshProvider");
  return ctx;
}
