import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { refresh, getRefreshStatus, cancelRefresh, uploadExport } from "../api";

const ACTIVE_STAGES = new Set(["starting", "scraping", "enriching", "profiling", "scoring"]);
const TERMINAL_STAGES = new Set(["done", "cancelled", "error"]);
const POLL_MS = 800;

const RefreshContext = createContext(null);

export function RefreshProvider({ username, children }) {
  const [status, setStatus] = useState(null);
  const [lastCompletedAt, setLastCompletedAt] = useState(null);
  const pollRef = useRef(null);
  const prevStageRef = useRef(null);
  const activeUserRef = useRef(null);

  // ProgressBar's timing anchors, owned here (not in ProgressBar) so they
  // survive the tab-switch remount — otherwise switching tabs mid-run resets
  // the elapsed clock and rewinds the percent back down.
  const startedAtRef = useRef(null);
  const stageRef = useRef(null);
  const stageStartRef = useRef(null);
  const maxPercentRef = useRef(0);
  const timing = useMemo(() => ({ startedAtRef, stageStartRef, maxPercentRef }), []);

  const resetTiming = useCallback(() => {
    startedAtRef.current = null;
    stageRef.current = null;
    stageStartRef.current = null;
    maxPercentRef.current = 0;
  }, []);

  const trackTiming = useCallback((s) => {
    const wasTerminal = TERMINAL_STAGES.has(stageRef.current);
    const isTerminal = TERMINAL_STAGES.has(s.stage);
    if (wasTerminal && !isTerminal) {
      // a fresh run started right after the previous one finished/errored/cancelled —
      // status never goes falsy between runs, so detect the edge explicitly
      startedAtRef.current = null;
      maxPercentRef.current = 0;
    }
    if (startedAtRef.current === null) startedAtRef.current = Date.now();
    if (stageRef.current !== s.stage) {
      stageRef.current = s.stage;
      stageStartRef.current = Date.now();
    }
  }, []);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const applyStatus = useCallback((s) => {
    trackTiming(s);
    setStatus(s);
    if (s.stage === "done" && ACTIVE_STAGES.has(prevStageRef.current)) {
      setLastCompletedAt(Date.now());
    }
    prevStageRef.current = s.stage;
    if (!ACTIVE_STAGES.has(s.stage)) {
      stopPolling();
    }
  }, [stopPolling, trackTiming]);

  const startPolling = useCallback((user) => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      let s;
      try {
        s = await getRefreshStatus(user);
      } catch {
        return; // transient poll failure, keep trying
      }
      if (user !== activeUserRef.current) return;
      applyStatus(s);
    }, POLL_MS);
  }, [applyStatus, stopPolling]);

  useEffect(() => {
    activeUserRef.current = username;
    stopPolling();
    setStatus(null);
    prevStageRef.current = null;
    resetTiming();
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
  }, [username, applyStatus, startPolling, stopPolling, resetTiming]);

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

  const startFromUpload = useCallback(async (file) => {
    if (!username) return { status: "no_username" };
    applyStatus({ stage: "starting", current: 0, total: null, message: "Importing your Letterboxd export..." });
    let res;
    try {
      res = await uploadExport(username, file);
    } catch {
      applyStatus({ stage: "error", current: 0, total: null, message: "Couldn't reach the backend to import the export. Is it running?" });
      return { status: "error" };
    }
    if (res.status === "started" || res.status === "already_running") {
      startPolling(username);
    } else {
      // 400s come back as {detail: "..."}
      applyStatus({ stage: "error", current: 0, total: null, message: res.detail || "Couldn't read that export file." });
    }
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
    <RefreshContext.Provider value={{ status, isRunning, start, startFromUpload, cancel, lastCompletedAt, timing }}>
      {children}
    </RefreshContext.Provider>
  );
}

export function useRefresh() {
  const ctx = useContext(RefreshContext);
  if (!ctx) throw new Error("useRefresh must be used within RefreshProvider");
  return ctx;
}
