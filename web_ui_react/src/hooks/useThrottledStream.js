export function createThrottledStreamController({ throttleMs = 120 } = {}) {
  let pendingChunkText = "";
  let pendingChunkRequestId = "";
  let flushTimer = null;

  const clearTimer = () => {
    if (flushTimer) {
      clearTimeout(flushTimer);
      flushTimer = null;
    }
  };

  const flush = ({ set, get }) => {
    if (!pendingChunkText) {
      clearTimer();
      return;
    }
    const chunk = pendingChunkText;
    const requestId = pendingChunkRequestId;
    pendingChunkText = "";
    pendingChunkRequestId = "";
    clearTimer();

    set((state) => {
      const currentRequestId = requestId || state.streamingRequestId;
      const switchedRequest = Boolean(state.streamingRequestId && state.streamingRequestId !== currentRequestId);
      return {
        streamingText: switchedRequest ? chunk : state.streamingText + chunk,
        streamingRequestId: currentRequestId,
        isStreaming: true,
      };
    });
  };

  const scheduleFlush = ({ set, get }) => {
    if (flushTimer) return;
    flushTimer = setTimeout(() => flush({ set, get }), throttleMs);
  };

  const setPending = (text = "", requestId = "") => {
    pendingChunkText = String(text || "");
    pendingChunkRequestId = String(requestId || "");
  };

  const reset = () => {
    pendingChunkText = "";
    pendingChunkRequestId = "";
    clearTimer();
  };

  return {
    flush,
    scheduleFlush,
    clearTimer,
    setPending,
    reset,
    getFlushTimer: () => flushTimer,
  };
}
