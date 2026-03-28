import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StatusBar } from "./StatusBar.jsx";

const mockStore = {
  sessionId: "session-abc",
  messages: [],
};

vi.mock("../hooks/useChatStore.js", () => ({
  useChatStore: () => mockStore,
}));

describe("StatusBar — bağlantı durumu göstergesi", () => {
  beforeEach(() => {
    mockStore.messages = [];
  });

  it("shows 🟢 Bağlı for connected status", () => {
    render(<StatusBar wsStatus="connected" onNewSession={vi.fn()} />);
    expect(screen.getByText(/🟢/)).toBeInTheDocument();
    expect(screen.getByText(/Bağlı/)).toBeInTheDocument();
  });

  it("shows 🟡 Bağlanıyor for connecting status", () => {
    render(<StatusBar wsStatus="connecting" onNewSession={vi.fn()} />);
    expect(screen.getByText(/🟡/)).toBeInTheDocument();
    expect(screen.getByText(/Bağlanıyor/)).toBeInTheDocument();
  });

  it("shows 🔴 Bağlantı kesildi for disconnected status", () => {
    render(<StatusBar wsStatus="disconnected" onNewSession={vi.fn()} />);
    expect(screen.getByText(/🔴/)).toBeInTheDocument();
    expect(screen.getByText(/Bağlantı kesildi/)).toBeInTheDocument();
  });

  it("shows 🔴 Hata for error status", () => {
    render(<StatusBar wsStatus="error" onNewSession={vi.fn()} />);
    expect(screen.getByText(/Hata/)).toBeInTheDocument();
  });

  it("shows 🟠 Token gerekli for unauthenticated status", () => {
    render(<StatusBar wsStatus="unauthenticated" onNewSession={vi.fn()} />);
    expect(screen.getByText(/🟠/)).toBeInTheDocument();
    expect(screen.getByText(/Token gerekli/)).toBeInTheDocument();
  });

  it("falls back to disconnected for unknown status", () => {
    render(<StatusBar wsStatus="unknown_xyz" onNewSession={vi.fn()} />);
    expect(screen.getByText(/Bağlantı kesildi/)).toBeInTheDocument();
  });
});

describe("StatusBar — mesaj sayacı", () => {
  it("shows 0 mesaj when messages array is empty", () => {
    mockStore.messages = [];
    render(<StatusBar wsStatus="connected" onNewSession={vi.fn()} />);
    expect(screen.getByText("0 mesaj")).toBeInTheDocument();
  });

  it("shows correct message count", () => {
    mockStore.messages = [{ id: 1 }, { id: 2 }, { id: 3 }];
    render(<StatusBar wsStatus="connected" onNewSession={vi.fn()} />);
    expect(screen.getByText("3 mesaj")).toBeInTheDocument();
  });
});

describe("StatusBar — workspace ve işbirlikçi bilgisi", () => {
  beforeEach(() => {
    mockStore.messages = [];
  });

  it("shows roomId when provided", () => {
    render(<StatusBar wsStatus="connected" onNewSession={vi.fn()} roomId="workspace:demo" />);
    expect(screen.getByText(/workspace:demo/)).toBeInTheDocument();
  });

  it("shows default workspace:sidar when roomId is empty", () => {
    render(<StatusBar wsStatus="connected" onNewSession={vi.fn()} roomId="" />);
    expect(screen.getByText(/workspace:sidar/)).toBeInTheDocument();
  });

  it("shows collaborator count", () => {
    render(<StatusBar wsStatus="connected" onNewSession={vi.fn()} collaborators={5} />);
    expect(screen.getByText(/5 kişi/)).toBeInTheDocument();
  });

  it("shows 0 collaborators by default", () => {
    render(<StatusBar wsStatus="connected" onNewSession={vi.fn()} />);
    expect(screen.getByText(/0 kişi/)).toBeInTheDocument();
  });
});

describe("StatusBar — ses durumu", () => {
  beforeEach(() => {
    mockStore.messages = [];
  });

  it("shows voiceStatus label", () => {
    render(<StatusBar wsStatus="connected" onNewSession={vi.fn()} voiceStatus="Dinliyor" />);
    expect(screen.getByText(/Dinliyor/)).toBeInTheDocument();
  });

  it("shows default 'Hazır' when voiceStatus not provided", () => {
    render(<StatusBar wsStatus="connected" onNewSession={vi.fn()} />);
    expect(screen.getByText(/Hazır/)).toBeInTheDocument();
  });
});

describe("StatusBar — yeni oturum butonu", () => {
  beforeEach(() => {
    mockStore.messages = [];
  });

  it("renders Yeni Oturum button", () => {
    render(<StatusBar wsStatus="connected" onNewSession={vi.fn()} />);
    expect(screen.getByRole("button", { name: /Yeni Oturum/ })).toBeInTheDocument();
  });

  it("calls onNewSession when button clicked", async () => {
    const user = userEvent.setup();
    const onNewSession = vi.fn();
    render(<StatusBar wsStatus="connected" onNewSession={onNewSession} />);
    await user.click(screen.getByRole("button", { name: /Yeni Oturum/ }));
    expect(onNewSession).toHaveBeenCalledTimes(1);
  });
});
