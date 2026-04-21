import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getStoredToken } from "../lib/api.js";

const VOICE_WS_URL = () =>
  `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/voice`;

const VAD_THRESHOLD = 0.035;
const VAD_SILENCE_MS = 640;
const MEDIA_TIMESLICE_MS = 250;

const createInitialState = () => ({
  status: "idle",
  summary: "Mikrofon beklemede. Duplex konuşma için hazır.",
  transcript: "",
  lastVoiceState: "idle",
  assistantTurnId: 0,
  bufferedBytes: 0,
  queueDepth: 0,
  audioMimeType: "",
  lastInterruptReason: "",
  diagnostics: [],
  isMicActive: false,
  isAssistantAudioPlaying: false,
  isAuthenticated: false,
  vad: {
    threshold: VAD_THRESHOLD,
    level: 0,
    speaking: false,
    silenceMs: 0,
  },
});

function appendDiagnostic(prev, label, value) {
  const entry = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    label,
    value,
    at: new Date().toLocaleTimeString("tr-TR"),
  };
  return [...prev.slice(-7), entry];
}

function statusSummary(status) {
  switch (status) {
    case "requesting_permission":
      return "Mikrofon erişimi isteniyor…";
    case "connecting_voice":
      return "Voice WebSocket bağlanıyor…";
    case "listening":
      return "Mikrofon açık. VAD konuşma başlangıcını izliyor.";
    case "capturing":
      return "Kullanıcı konuşuyor. Ses parçaları canlı olarak gönderiliyor.";
    case "processing":
      return "Sunucu yeni ses dönüşünü işliyor.";
    case "playing":
      return "SİDAR konuşuyor. Araya girerseniz oynatma anında kesilir.";
    case "interrupted":
      return "SİDAR sesi kesildi. Yeni kullanıcı bağlamı gönderiliyor.";
    case "unauthenticated":
      return "Voice websocket için Bearer token gerekli.";
    case "error":
      return "Ses akışında hata oluştu.";
    default:
      return "Mikrofon beklemede. Duplex konuşma için hazır.";
  }
}

export const __voiceAssistantTestables = {
  statusSummary,
};

function toBase64(arrayBuffer) {
  const bytes = new Uint8Array(arrayBuffer);
  let binary = "";
  const chunk = 0x8000;
  for (let index = 0; index < bytes.length; index += chunk) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunk));
  }
  return btoa(binary);
}

function fromBase64(base64) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

function pickRecorderMimeType() {
  /* c8 ignore next */
  if (typeof MediaRecorder === "undefined") return "audio/webm";
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
  ];
  return candidates.find((mimeType) => MediaRecorder.isTypeSupported?.(mimeType)) || "audio/webm";
}

export function useVoiceAssistant({
  onUserTranscript,
  onAssistantChunk,
  onAssistantDone,
  onError,
  onTelemetry,
} = {}) {
  const [state, setState] = useState(createInitialState);
  const wsRef = useRef(null);
  const wsReadyPromiseRef = useRef(null);
  const analyserRef = useRef(null);
  const audioContextRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const mediaStreamRef = useRef(null);
  const rafRef = useRef(0);
  const speechActiveRef = useRef(false);
  const turnActiveRef = useRef(false);
  const pendingCommitRef = useRef(false);
  const commitTimeoutRef = useRef(0);
  const lastSpeechAtRef = useRef(0);
  const audioQueueRef = useRef([]);
  const activeAudioRef = useRef(null);
  const revokeUrlsRef = useRef(new Set());
  const unmountedRef = useRef(false);
  const stateRef = useRef(createInitialState());

  const setVoiceState = useCallback((patch) => {
    setState((prev) => {
      const next = {
        ...prev,
        ...patch,
        vad: {
          ...prev.vad,
          ...(patch?.vad || {}),
        },
      };
      stateRef.current = next;
      return next;
    });
  }, []);

  const pushDiagnostic = useCallback((label, value) => {
    setState((prev) => {
      const next = {
        ...prev,
        diagnostics: appendDiagnostic(prev.diagnostics, label, value),
      };
      stateRef.current = next;
      return next;
    });
  }, []);

  const setStatus = useCallback((status, summary = statusSummary(status)) => {
    setVoiceState({ status, summary });
  }, [setVoiceState]);

  const stopPlayback = useCallback((reason = "") => {
    if (activeAudioRef.current) {
      activeAudioRef.current.pause();
      activeAudioRef.current.currentTime = 0;
      activeAudioRef.current = null;
    }
    for (const item of audioQueueRef.current) {
      if (item.url) {
        URL.revokeObjectURL(item.url);
      }
    }
    audioQueueRef.current = [];
    for (const url of revokeUrlsRef.current) {
      URL.revokeObjectURL(url);
    }
    revokeUrlsRef.current.clear();
    setVoiceState({
      isAssistantAudioPlaying: false,
      queueDepth: 0,
      lastInterruptReason: reason,
    });
  }, [setVoiceState]);

  const playNextAudio = useCallback(() => {
    if (activeAudioRef.current || audioQueueRef.current.length === 0) {
      return;
    }
    const nextItem = audioQueueRef.current.splice(0, 1)[0];

    const audio = new Audio(nextItem.url);
    activeAudioRef.current = audio;
    setStatus("playing");
    setVoiceState({
      isAssistantAudioPlaying: true,
      queueDepth: audioQueueRef.current.length + 1,
      audioMimeType: nextItem.mimeType,
    });

    const finalize = () => {
      audio.pause();
      activeAudioRef.current = null;
      if (revokeUrlsRef.current.has(nextItem.url)) {
        URL.revokeObjectURL(nextItem.url);
        revokeUrlsRef.current.delete(nextItem.url);
      }
      if (audioQueueRef.current.length > 0) {
        setVoiceState({ queueDepth: audioQueueRef.current.length });
        playNextAudio();
      } else {
        setVoiceState({ isAssistantAudioPlaying: false, queueDepth: 0 });
        if (stateRef.current.isMicActive) {
          setStatus("listening");
        }
      }
    };

    audio.onended = finalize;
    audio.onerror = () => {
      pushDiagnostic("Ses oynatma", "Tarayıcı TTS ses parçasını oynatamadı.");
      finalize();
    };
    audio.play().catch(() => {
      pushDiagnostic("Ses oynatma", "Otomatik oynatma engellendi; yeni ses sırası beklemede.");
      finalize();
    });
  }, [pushDiagnostic, setStatus, setVoiceState]);

  const queueAudioChunk = useCallback((base64, mimeType) => {
    try {
      const bytes = fromBase64(base64);
      const resolvedMimeType = mimeType || "audio/wav";
      const blob = new Blob([bytes], { type: resolvedMimeType });
      const url = URL.createObjectURL(blob);
      revokeUrlsRef.current.add(url);
      audioQueueRef.current.push({ url, mimeType: resolvedMimeType });
      setVoiceState({
        queueDepth: audioQueueRef.current.length,
        isAssistantAudioPlaying: true,
        audioMimeType: resolvedMimeType,
      });
      playNextAudio();
    } catch (error) {
      onError?.(`Ses parçası çözülemedi: ${error instanceof Error ? error.message : String(error)}`);
    }
  }, [onError, playNextAudio, setVoiceState]);

  const sendJson = useCallback((payload) => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) {
      return false;
    }
    wsRef.current.send(JSON.stringify(payload));
    return true;
  }, []);

  const handleDone = useCallback(() => {
    onAssistantDone?.();
    if (!stateRef.current.isAssistantAudioPlaying) {
      setStatus(stateRef.current.isMicActive ? "listening" : "idle");
    }
  }, [onAssistantDone, setStatus]);

  const ensureVoiceSocket = useCallback(async () => {
    if (wsRef.current?.readyState === WebSocket.OPEN && stateRef.current.isAuthenticated) {
      return wsRef.current;
    }
    if (wsReadyPromiseRef.current) {
      return wsReadyPromiseRef.current;
    }

    const token = getStoredToken();
    if (!token) {
      setStatus("unauthenticated");
      onError?.("Voice websocket için önce Bearer token kaydedin.");
      throw new Error("Missing token");
    }

    setStatus("connecting_voice");
    wsReadyPromiseRef.current = new Promise((resolve, reject) => {
      const ws = new WebSocket(VOICE_WS_URL(), [token]);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        let msg;
        try {
          msg = JSON.parse(event.data);
        } catch {
          return;
        }

        if (msg.auth_ok) {
          setVoiceState({ isAuthenticated: true });
          pushDiagnostic("Voice auth", "WebSocket kimlik doğrulaması tamamlandı.");
          resolve(ws);
          return;
        }
        if (msg.voice_session === "ready") {
          setStatus("listening", "Voice oturumu hazır. Konuşmaya başlayabilirsiniz.");
          setVoiceState({
            lastVoiceState: "ready",
            bufferedBytes: 0,
          });
          return;
        }
        if (typeof msg.buffered_bytes === "number") {
          setVoiceState({ bufferedBytes: msg.buffered_bytes });
        }
        if (msg.voice_state) {
          const nextStatus = msg.voice_state === "processed"
            ? "processing"
            : msg.voice_state === "speech_start"
              ? "capturing"
              : stateRef.current.isAssistantAudioPlaying
                ? "playing"
                : stateRef.current.isMicActive
                  ? "listening"
                  : stateRef.current.status;
          setVoiceState({
            lastVoiceState: msg.voice_state,
            assistantTurnId: Number(msg.assistant_turn_id || stateRef.current.assistantTurnId || 0),
            bufferedBytes: Number(msg.buffered_bytes || stateRef.current.bufferedBytes || 0),
            lastInterruptReason: String(msg.last_interrupt_reason || stateRef.current.lastInterruptReason || ""),
          });
          setStatus(nextStatus, `Voice durum: ${msg.voice_state}`);
          return;
        }
        if (msg.voice_interruption) {
          stopPlayback(String(msg.voice_interruption));
          setStatus("interrupted", `SİDAR sesi kesildi: ${msg.voice_interruption}`);
          pushDiagnostic("Kesinti", `${msg.voice_interruption} · iptal edilen ses #${msg.cancelled_audio_sequences ?? 0}`);
          return;
        }
        if (msg.assistant_turn === "started") {
          setVoiceState({ assistantTurnId: Number(msg.assistant_turn_id || 0) });
          return;
        }
        if (typeof msg.transcript === "string") {
          const transcript = String(msg.transcript || "").trim();
          setVoiceState({ transcript, bufferedBytes: 0 });
          if (transcript) {
            onUserTranscript?.(transcript);
            pushDiagnostic("Transcript", transcript);
          }
          return;
        }
        if (typeof msg.chunk === "string") {
          onAssistantChunk?.(msg.chunk);
          return;
        }
        if (typeof msg.audio_chunk === "string") {
          queueAudioChunk(msg.audio_chunk, msg.audio_mime_type);
          return;
        }
        if (msg.done === true) {
          handleDone();
          return;
        }
        if (typeof msg.error === "string") {
          setStatus("error", msg.error);
          pushDiagnostic("Voice hata", msg.error);
          onError?.(msg.error);
        }
      };

      ws.onerror = () => {
        setStatus("error", "Voice websocket bağlantı hatası.");
        const error = new Error("Voice websocket error");
        reject(error);
      };

      ws.onclose = () => {
        wsReadyPromiseRef.current = null;
        wsRef.current = null;
        setVoiceState({ isAuthenticated: false, bufferedBytes: 0 });
        if (!unmountedRef.current && stateRef.current.isMicActive) {
          setStatus("error", "Voice websocket bağlantısı kapandı.");
        }
      };
    }).finally(() => {
      wsReadyPromiseRef.current = null;
    });

    return wsReadyPromiseRef.current;
  }, [handleDone, onAssistantChunk, onError, onUserTranscript, pushDiagnostic, queueAudioChunk, setStatus, setVoiceState, stopPlayback]);

  const beginVoiceTurn = useCallback(async ({ interrupt = false } = {}) => {
    const ws = await ensureVoiceSocket();
    if (interrupt) {
      sendJson({ action: "cancel" });
      pushDiagnostic("Barge-in", "Kullanıcı araya girdi; oynatma istemci tarafında kesildi.");
    }
    ws.send(JSON.stringify({
      action: "start",
      mime_type: pickRecorderMimeType(),
      language: "tr",
    }));
    turnActiveRef.current = true;
  }, [ensureVoiceSocket, pushDiagnostic, sendJson]);

  const flushCommit = useCallback(() => {
    if (!pendingCommitRef.current || !turnActiveRef.current) {
      return;
    }
    pendingCommitRef.current = false;
    turnActiveRef.current = false;
    window.clearTimeout(commitTimeoutRef.current);
    sendJson({ action: "commit", mime_type: pickRecorderMimeType(), language: "tr" });
    setStatus("processing");
  }, [sendJson, setStatus]);

  const handleSpeechStart = useCallback(async () => {
    speechActiveRef.current = true;
    lastSpeechAtRef.current = Date.now();
    const interrupting = stateRef.current.isAssistantAudioPlaying;
    if (interrupting) {
      stopPlayback("barge_in_local");
      setStatus("interrupted");
    } else {
      setStatus("capturing");
    }
    await beginVoiceTurn({ interrupt: interrupting || stateRef.current.lastVoiceState === "processed" });
    sendJson({ action: "vad_event", state: "speech_start" });
  }, [beginVoiceTurn, sendJson, setStatus, stopPlayback]);

  const handleSpeechEnd = useCallback(() => {
    /* c8 ignore next */
    if (!speechActiveRef.current || !turnActiveRef.current) return;
    speechActiveRef.current = false;
    pendingCommitRef.current = true;
    sendJson({ action: "vad_event", state: "speech_end" });
    mediaRecorderRef.current?.requestData?.();
    window.clearTimeout(commitTimeoutRef.current);
    commitTimeoutRef.current = window.setTimeout(() => {
      flushCommit();
    }, 180);
    setStatus("processing", "Konuşma bitti. Son parça gönderilip işlenecek.");
  }, [flushCommit, sendJson, setStatus]);

  const pumpVad = useCallback(() => {
    const loop = () => {
      if (!analyserRef.current) return;
      const analyser = analyserRef.current;
      const frame = new Uint8Array(analyser.fftSize);
      analyser.getByteTimeDomainData(frame);
      let sumSquares = 0;
      for (let index = 0; index < frame.length; index += 1) {
        const centered = (frame[index] - 128) / 128;
        sumSquares += centered * centered;
      }
      const rms = Math.sqrt(sumSquares / frame.length);
      const now = Date.now();
      const speaking = rms >= VAD_THRESHOLD;

      if (speaking) {
        lastSpeechAtRef.current = now;
        if (!speechActiveRef.current) {
          void handleSpeechStart();
        }
      } else if (speechActiveRef.current) {
        const silenceMs = now - lastSpeechAtRef.current;
        if (silenceMs >= VAD_SILENCE_MS) {
          handleSpeechEnd();
        }
        setVoiceState({ vad: { silenceMs } });
      }

      setVoiceState({
        vad: {
          level: Number(rms.toFixed(4)),
          speaking,
          silenceMs: speaking ? 0 : Math.max(0, now - lastSpeechAtRef.current),
        },
      });
      rafRef.current = window.requestAnimationFrame(loop);
    };

    rafRef.current = window.requestAnimationFrame(loop);
  }, [handleSpeechEnd, handleSpeechStart, setVoiceState]);

  const cleanupMic = useCallback(() => {
    window.cancelAnimationFrame(rafRef.current);
    rafRef.current = 0;
    window.clearTimeout(commitTimeoutRef.current);
    commitTimeoutRef.current = 0;
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      mediaRecorderRef.current.stop();
    }
    mediaRecorderRef.current = null;
    analyserRef.current = null;
    if (audioContextRef.current) {
      audioContextRef.current.close().catch(() => {});
    }
    audioContextRef.current = null;
    if (mediaStreamRef.current && typeof mediaStreamRef.current.getTracks === "function") {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
    }
    mediaStreamRef.current = null;
    speechActiveRef.current = false;
    pendingCommitRef.current = false;
    turnActiveRef.current = false;
    setVoiceState({
      isMicActive: false,
      bufferedBytes: 0,
      vad: { level: 0, speaking: false, silenceMs: 0 },
    });
  }, [setVoiceState]);

  const start = useCallback(async () => {
    if (stateRef.current.isMicActive) return;
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      const message = "Tarayıcı mikrofon veya MediaRecorder API desteği sunmuyor.";
      setStatus("error", message);
      onError?.(message);
      return;
    }

    setStatus("requesting_permission");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
      });
      const context = new AudioContext();
      const source = context.createMediaStreamSource(stream);
      const analyser = context.createAnalyser();
      analyser.fftSize = 2048;
      analyser.smoothingTimeConstant = 0.82;
      source.connect(analyser);

      const recorder = new MediaRecorder(stream, { mimeType: pickRecorderMimeType() });
      recorder.ondataavailable = async (event) => {
        if (!event.data || event.data.size === 0 || !turnActiveRef.current) {
          return;
        }
        try {
          const arrayBuffer = await event.data.arrayBuffer();
          if (!turnActiveRef.current) {
            return;
          }
          sendJson({ action: "append_base64", chunk: toBase64(arrayBuffer) });
          if (pendingCommitRef.current) {
            flushCommit();
          }
        } catch (error) {
          onError?.(`Mikrofon verisi gönderilemedi: ${error instanceof Error ? error.message : String(error)}`);
        }
      };
      recorder.start(MEDIA_TIMESLICE_MS);

      mediaStreamRef.current = stream;
      audioContextRef.current = context;
      analyserRef.current = analyser;
      mediaRecorderRef.current = recorder;
      setVoiceState({ isMicActive: true, transcript: "" });
      setStatus("listening");
      pushDiagnostic("Mikrofon", "Canlı VAD izleme başlatıldı.");
      pumpVad();
      void ensureVoiceSocket().catch(() => {});
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setStatus("error", `Mikrofon başlatılamadı: ${message}`);
      onError?.(`Mikrofon başlatılamadı: ${message}`);
    }
  }, [ensureVoiceSocket, flushCommit, onError, pumpVad, pushDiagnostic, sendJson, setStatus, setVoiceState]);

  const stop = useCallback(() => {
    cleanupMic();
    stopPlayback("session_stopped");
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      sendJson({ action: "cancel" });
    }
    setStatus("idle");
  }, [cleanupMic, sendJson, setStatus, stopPlayback]);

  const toggle = useCallback(() => {
    if (stateRef.current.isMicActive) {
      stop();
    } else {
      void start();
    }
  }, [start, stop]);

  const interrupt = useCallback(() => {
    stopPlayback("manual_interrupt");
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      sendJson({ action: "cancel" });
    }
    pushDiagnostic("Manuel kesinti", "Kullanıcı mevcut SİDAR sesini durdurdu.");
    setStatus(stateRef.current.isMicActive ? "listening" : "idle");
  }, [pushDiagnostic, sendJson, setStatus, stopPlayback]);

  useEffect(() => {
    onTelemetry?.("voice_status", `${state.status}:${state.lastVoiceState}:${state.bufferedBytes}`);
  }, [onTelemetry, state.bufferedBytes, state.lastVoiceState, state.status]);

  useEffect(() => () => {
    unmountedRef.current = true;
    cleanupMic();
    stopPlayback("unmount");
    wsRef.current?.close();
  }, [cleanupMic, stopPlayback]);

  const statusLabel = useMemo(() => {
    switch (state.status) {
      case "listening":
        return "Dinliyor";
      case "capturing":
        return "Konuşma algılandı";
      case "processing":
        return "İşleniyor";
      case "playing":
        return "SİDAR konuşuyor";
      case "interrupted":
        return "Kesildi";
      case "connecting_voice":
        return "Voice WS";
      case "requesting_permission":
        return "İzin";
      case "error":
        return "Hata";
      case "unauthenticated":
        return "Token gerekli";
      default:
        return "Hazır";
    }
  }, [state.status]);

  return {
    state,
    statusLabel,
    toggle,
    start,
    stop,
    interrupt,
    supported: Boolean(navigator.mediaDevices?.getUserMedia) && typeof MediaRecorder !== "undefined",
  };
}
