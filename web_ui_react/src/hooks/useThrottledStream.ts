export interface StreamChunkState {
  streamingText: string;
  streamingRequestId: string;
  isStreaming: boolean;
}

export type StreamStateSetter = (
  updater: (state: StreamChunkState) => Partial<StreamChunkState>
) => void;
export type StreamStateGetter = () => StreamChunkState;

export interface StreamSetGet {
  set: StreamStateSetter;
  get: StreamStateGetter;
}

export interface ThrottledStreamController {
  flush: (setGet: StreamSetGet) => void;
  scheduleFlush: (setGet: StreamSetGet) => void;
  clearTimer: () => void;
  setPending: (text?: string, requestId?: string) => void;
  reset: () => void;
  getFlushTimer: () => ReturnType<typeof setTimeout> | null;
}

export interface ThrottledStreamControllerOptions {
  throttleMs?: number;
}

export function createThrottledStreamController({
  throttleMs = 120,
}: ThrottledStreamControllerOptions = {}): ThrottledStreamController {
  let pendingChunkText = "";
  let pendingChunkRequestId = "";
  let flushTimer: ReturnType<typeof setTimeout> | null = null;

  const clearTimer = (): void => {
    if (flushTimer) {
      clearTimeout(flushTimer);
      flushTimer = null;
    }
  };

  const flush = ({ set }: StreamSetGet): void => {
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
      const switchedRequest = Boolean(
        state.streamingRequestId && state.streamingRequestId !== currentRequestId
      );
      return {
        streamingText: switchedRequest ? chunk : state.streamingText + chunk,
        streamingRequestId: currentRequestId,
        isStreaming: true,
      };
    });
  };

  const scheduleFlush = (setGet: StreamSetGet): void => {
    if (flushTimer) return;
    flushTimer = setTimeout(() => flush(setGet), throttleMs);
  };

  const setPending = (text = "", requestId = ""): void => {
    pendingChunkText = String(text || "");
    pendingChunkRequestId = String(requestId || "");
  };

  const reset = (): void => {
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
