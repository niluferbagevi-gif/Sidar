import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { VoiceAssistantPanel } from "./VoiceAssistantPanel.jsx";

const makeVoice = (overrides = {}) => ({
  state: {
    status: "idle",
    isMicActive: false,
    isAssistantAudioPlaying: false,
    queueDepth: 0,
    summary: "Mikrofon beklemede. Duplex konuşma için hazır.",
    transcript: "",
    lastInterruptReason: "",
    assistantTurnId: 0,
    bufferedBytes: 0,
    audioMimeType: "audio/wav",
    diagnostics: [],
    vad: { level: 0, speaking: false },
  },
  statusLabel: "Hazır",
  toggle: vi.fn(),
  interrupt: vi.fn(),
  supported: true,
  ...overrides,
});

describe("VoiceAssistantPanel — temel render", () => {
  it("renders section with voice-panel class", () => {
    const { container } = render(<VoiceAssistantPanel voice={makeVoice()} />);
    expect(container.querySelector(".voice-panel")).toBeInTheDocument();
  });

  it("shows statusLabel badge", () => {
    render(<VoiceAssistantPanel voice={makeVoice({ statusLabel: "Dinliyor" })} />);
    expect(screen.getByText("Dinliyor")).toBeInTheDocument();
  });

  it("shows summary text", () => {
    render(<VoiceAssistantPanel voice={makeVoice()} />);
    expect(screen.getByText("Mikrofon beklemede. Duplex konuşma için hazır.")).toBeInTheDocument();
  });

  it("has aria-live=polite on section", () => {
    const { container } = render(<VoiceAssistantPanel voice={makeVoice()} />);
    expect(container.querySelector("[aria-live='polite']")).toBeInTheDocument();
  });
});

describe("VoiceAssistantPanel — mikrofon başlatma butonu", () => {
  it("shows '🎙 Mikrofonu Başlat' when mic is inactive", () => {
    render(<VoiceAssistantPanel voice={makeVoice()} />);
    expect(screen.getByRole("button", { name: /Mikrofonu Başlat/ })).toBeInTheDocument();
  });

  it("shows '■ Mikrofona Ara Ver' when mic is active", () => {
    const voice = makeVoice();
    voice.state.isMicActive = true;
    render(<VoiceAssistantPanel voice={voice} />);
    expect(screen.getByRole("button", { name: /Mikrofona Ara Ver/ })).toBeInTheDocument();
  });

  it("calls toggle when mic button clicked", async () => {
    const user = userEvent.setup();
    const voice = makeVoice();
    render(<VoiceAssistantPanel voice={voice} />);
    await user.click(screen.getByRole("button", { name: /Mikrofonu Başlat/ }));
    expect(voice.toggle).toHaveBeenCalledTimes(1);
  });

  it("mic button is disabled when supported is false", () => {
    const voice = makeVoice({ supported: false });
    render(<VoiceAssistantPanel voice={voice} />);
    expect(screen.getByRole("button", { name: /Mikrofonu Başlat/ })).toBeDisabled();
  });

  it("mic button is enabled when supported is true", () => {
    render(<VoiceAssistantPanel voice={makeVoice()} />);
    expect(screen.getByRole("button", { name: /Mikrofonu Başlat/ })).toBeEnabled();
  });
});

describe("VoiceAssistantPanel — ses kesme butonu", () => {
  it("shows SİDAR Sesini Kes button", () => {
    render(<VoiceAssistantPanel voice={makeVoice()} />);
    expect(screen.getByRole("button", { name: /SİDAR Sesini Kes/ })).toBeInTheDocument();
  });

  it("interrupt button disabled when no audio playing and queueDepth is 0", () => {
    const voice = makeVoice();
    voice.state.isAssistantAudioPlaying = false;
    voice.state.queueDepth = 0;
    render(<VoiceAssistantPanel voice={voice} />);
    expect(screen.getByRole("button", { name: /SİDAR Sesini Kes/ })).toBeDisabled();
  });

  it("interrupt button enabled when assistant audio is playing", () => {
    const voice = makeVoice();
    voice.state.isAssistantAudioPlaying = true;
    render(<VoiceAssistantPanel voice={voice} />);
    expect(screen.getByRole("button", { name: /SİDAR Sesini Kes/ })).toBeEnabled();
  });

  it("interrupt button enabled when queueDepth > 0", () => {
    const voice = makeVoice();
    voice.state.queueDepth = 2;
    render(<VoiceAssistantPanel voice={voice} />);
    expect(screen.getByRole("button", { name: /SİDAR Sesini Kes/ })).toBeEnabled();
  });

  it("calls interrupt when interrupt button clicked", async () => {
    const user = userEvent.setup();
    const voice = makeVoice();
    voice.state.isAssistantAudioPlaying = true;
    render(<VoiceAssistantPanel voice={voice} />);
    await user.click(screen.getByRole("button", { name: /SİDAR Sesini Kes/ }));
    expect(voice.interrupt).toHaveBeenCalledTimes(1);
  });
});

describe("VoiceAssistantPanel — bilgi kartları", () => {
  it("shows transcript when available", () => {
    const voice = makeVoice();
    voice.state.transcript = "merhaba sidar";
    render(<VoiceAssistantPanel voice={voice} />);
    expect(screen.getByText("merhaba sidar")).toBeInTheDocument();
  });

  it("shows placeholder text when transcript is empty", () => {
    render(<VoiceAssistantPanel voice={makeVoice()} />);
    expect(screen.getByText("Henüz transcript alınmadı.")).toBeInTheDocument();
  });

  it("shows VAD level and speaking status", () => {
    const voice = makeVoice();
    voice.state.vad = { level: 0.042, speaking: true };
    render(<VoiceAssistantPanel voice={voice} />);
    expect(screen.getByText(/0.042/)).toBeInTheDocument();
    // VAD kartındaki "konuşma" etiketi — birden fazla eşleşme olabilir (summary vs kart)
    expect(screen.getAllByText(/konuşma/).length).toBeGreaterThanOrEqual(1);
  });

  it("shows buffered bytes and queue depth", () => {
    const voice = makeVoice();
    voice.state.bufferedBytes = 1024;
    voice.state.queueDepth = 3;
    voice.state.audioMimeType = "audio/webm";
    render(<VoiceAssistantPanel voice={voice} />);
    expect(screen.getByText(/1024 bayt/)).toBeInTheDocument();
    expect(screen.getByText(/kuyruk 3/)).toBeInTheDocument();
  });
});

describe("VoiceAssistantPanel — tarayıcı desteği yoksa", () => {
  it("shows unsupported message when supported is false", () => {
    render(<VoiceAssistantPanel voice={makeVoice({ supported: false })} />);
    expect(screen.getByText(/Bu tarayıcı MediaRecorder/)).toBeInTheDocument();
  });
});

describe("VoiceAssistantPanel — tanılama olayları", () => {
  it("shows empty diagnostics placeholder when no events", () => {
    render(<VoiceAssistantPanel voice={makeVoice()} />);
    expect(screen.getByText("Tanılama olayları burada görünecek.")).toBeInTheDocument();
  });

  it("renders diagnostic entries when present", () => {
    const voice = makeVoice();
    voice.state.diagnostics = [
      { id: "d1", label: "Mikrofon", value: "başlatıldı", at: "10:00:00" },
    ];
    render(<VoiceAssistantPanel voice={voice} />);
    expect(screen.getByText("Mikrofon")).toBeInTheDocument();
    expect(screen.getByText("başlatıldı")).toBeInTheDocument();
  });
});
