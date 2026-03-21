import "../../../web_ui/voice_live_utils.js";

const {
  VOICE_STATE_LABELS,
  appendVoiceLog,
  buildVoiceDiagnosticsText,
  getVoiceBadgeMeta,
  getVoiceLiveDefaults,
} = window.SidarVoiceLiveUtils;

describe("voice_live_utils", () => {
  it("returns stable defaults for the legacy voice live panel", () => {
    expect(getVoiceLiveDefaults()).toEqual({
      lastTranscript: "",
      lastState: "idle",
      summary: "Ses websocket tanılama verisi bekleniyor.",
      diagnostics: "Henüz ek tanı verisi yok.",
      badgeClass: "idle",
      badgeLabel: "Bekleniyor",
      log: [],
    });
    expect(VOICE_STATE_LABELS.processed).toBe("İşlendi");
  });

  it("derives badge state from transcript, completion, and interruption payloads", () => {
    expect(getVoiceBadgeMeta("ready", {})).toEqual({ badgeClass: "listening", badgeLabel: "Canlı" });
    expect(getVoiceBadgeMeta("idle", { transcript: "merhaba" })).toEqual({ badgeClass: "processing", badgeLabel: "İşleniyor" });
    expect(getVoiceBadgeMeta("processed", { done: true })).toEqual({ badgeClass: "complete", badgeLabel: "Tamamlandı" });
    expect(getVoiceBadgeMeta("cancelled", { voice_interruption: "user" })).toEqual({ badgeClass: "error", badgeLabel: "Kesildi" });
  });

  it("formats diagnostics and caps the rolling log list", () => {
    expect(buildVoiceDiagnosticsText({
      buffered_bytes: 512,
      sequence: 4,
      assistant_turn_id: 3,
      provider: "openai",
      interrupt_ready: true,
    })).toContain("buffer 512 B · seq 4 · tur 3 · sağlayıcı openai · barge-in hazır");

    const log = Array.from({ length: 10 }, (_, index) => ({ label: `L${index}`, value: `${index}` }));
    const next = appendVoiceLog(log, "Yeni", "olay");
    expect(next).toHaveLength(8);
    expect(next[0]).toEqual({ label: "Yeni", value: "olay" });
  });
});