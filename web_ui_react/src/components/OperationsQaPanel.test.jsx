import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { OperationsQaPanel } from "./OperationsQaPanel.jsx";

const apiMocks = vi.hoisted(() => ({
  analyzeCoverage: vi.fn(),
  generateCampaignCopy: vi.fn(),
  generateLandingPage: vi.fn(),
  listHitlPending: vi.fn(),
  respondHitl: vi.fn(),
  runCoverageBatch: vi.fn(),
}));

vi.mock("../lib/api.js", () => apiMocks);

let webSocketOptions = {};
const wsState = { status: "connected" };

vi.mock("../hooks/useWebSocket.js", () => ({
  useWebSocket: (sessionId, options) => {
    webSocketOptions = options;
    return { send: vi.fn(), status: wsState.status };
  },
}));

const resolved = (payload) => Promise.resolve(payload);

beforeEach(() => {
  apiMocks.analyzeCoverage.mockReset();
  apiMocks.generateCampaignCopy.mockReset();
  apiMocks.generateLandingPage.mockReset();
  apiMocks.listHitlPending.mockReset();
  apiMocks.respondHitl.mockReset();
  apiMocks.runCoverageBatch.mockReset();
  apiMocks.listHitlPending.mockResolvedValue({ pending: [] });
  webSocketOptions = {};
  wsState.status = "connected";
});

describe("OperationsQaPanel — başlangıç render", () => {
  it("paneli ve oda anahtarını oluşturur", async () => {
    render(<OperationsQaPanel />);
    expect(screen.getByText("Poyraz & Coverage Kontrol Paneli")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Oda: ops:control/i })).toBeInTheDocument();
    await waitFor(() => expect(apiMocks.listHitlPending).toHaveBeenCalled());
  });

  it("WS durum chip'ini gösterir", () => {
    wsState.status = "disconnected";
    render(<OperationsQaPanel />);
    expect(screen.getByText("WS: disconnected")).toBeInTheDocument();
  });

  it("oda değiştirme butonu aktif odayı değiştirir", async () => {
    const user = userEvent.setup();
    render(<OperationsQaPanel />);
    const toggle = screen.getByRole("button", { name: /Oda: ops:control/i });
    await user.click(toggle);
    expect(screen.getByRole("button", { name: /Oda: qa:coverage/i })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Oda: qa:coverage/i }));
    expect(screen.getByRole("button", { name: /Oda: ops:control/i })).toBeInTheDocument();
  });
});

describe("OperationsQaPanel — REST tetiklemeleri", () => {
  it("Landing page formu generateLandingPage çağırır", async () => {
    const user = userEvent.setup();
    apiMocks.generateLandingPage.mockResolvedValue({ ok: true, page: "<html/>" });
    render(<OperationsQaPanel />);

    await user.click(screen.getByRole("button", { name: "Landing üret" }));

    await waitFor(() => expect(apiMocks.generateLandingPage).toHaveBeenCalledTimes(1));
    const payload = apiMocks.generateLandingPage.mock.calls[0][0];
    expect(payload.room_id).toBe("ops:control");
    expect(payload.brand_name).toBe("Sidar");
    expect(await screen.findByText("Landing page tamamlandı.")).toBeInTheDocument();
  });

  it("kampanya kopyası kanalları virgülle parse eder", async () => {
    const user = userEvent.setup();
    apiMocks.generateCampaignCopy.mockResolvedValue({ ok: true });
    render(<OperationsQaPanel />);

    await user.click(screen.getByRole("button", { name: "Kopya üret" }));

    await waitFor(() => expect(apiMocks.generateCampaignCopy).toHaveBeenCalledTimes(1));
    const payload = apiMocks.generateCampaignCopy.mock.calls[0][0];
    expect(payload.channels).toEqual(["LinkedIn", "email"]);
    expect(payload.room_id).toBe("ops:control");
  });

  it("Coverage analizi formu analyzeCoverage çağırır", async () => {
    const user = userEvent.setup();
    apiMocks.analyzeCoverage.mockResolvedValue({ ok: true });
    render(<OperationsQaPanel />);

    await user.click(screen.getByRole("button", { name: "Analiz et" }));

    await waitFor(() => expect(apiMocks.analyzeCoverage).toHaveBeenCalledTimes(1));
    const payload = apiMocks.analyzeCoverage.mock.calls[0][0];
    expect(payload.room_id).toBe("qa:coverage");
    expect(payload.coverage_xml).toBe("coverage.xml");
    expect(payload.limit).toBe(10);
  });

  it("Coverage batch formu runCoverageBatch çağırır", async () => {
    const user = userEvent.setup();
    apiMocks.runCoverageBatch.mockResolvedValue({ ok: true });
    render(<OperationsQaPanel />);

    await user.click(screen.getByRole("button", { name: "Batch çalıştır" }));

    await waitFor(() => expect(apiMocks.runCoverageBatch).toHaveBeenCalledTimes(1));
    const payload = apiMocks.runCoverageBatch.mock.calls[0][0];
    expect(payload.room_id).toBe("qa:coverage");
    expect(payload.append).toBe(true);
    expect(payload.batch_size).toBe(1);
  });

  it("REST hatasını banner olarak gösterir", async () => {
    const user = userEvent.setup();
    apiMocks.generateLandingPage.mockRejectedValue(new Error("Landing patladı"));
    render(<OperationsQaPanel />);

    await user.click(screen.getByRole("button", { name: "Landing üret" }));

    expect(await screen.findByText("Landing patladı")).toBeInTheDocument();
    expect(await screen.findByText("Landing page başarısız.")).toBeInTheDocument();
  });
});

describe("OperationsQaPanel — form girdileri", () => {
  it("Landing form alanları kontrollü güncellenir", async () => {
    const user = userEvent.setup();
    apiMocks.generateLandingPage.mockResolvedValue({ ok: true });
    render(<OperationsQaPanel />);
    const offerInputs = screen.getAllByRole("textbox", { name: "offer" });
    const landingOffer = offerInputs[0];
    await user.clear(landingOffer);
    await user.type(landingOffer, "Yeni teklif");
    expect(landingOffer).toHaveValue("Yeni teklif");
    await user.click(screen.getByRole("button", { name: "Landing üret" }));
    await waitFor(() => expect(apiMocks.generateLandingPage).toHaveBeenCalled());
    expect(apiMocks.generateLandingPage.mock.calls[0][0].offer).toBe("Yeni teklif");
  });

  it("Coverage batch append checkbox değiştirilebilir", async () => {
    const user = userEvent.setup();
    apiMocks.runCoverageBatch.mockResolvedValue({ ok: true });
    render(<OperationsQaPanel />);
    const appendCheckbox = screen.getByRole("checkbox", { name: /append/i });
    expect(appendCheckbox).toBeChecked();
    await user.click(appendCheckbox);
    expect(appendCheckbox).not.toBeChecked();
    await user.click(screen.getByRole("button", { name: "Batch çalıştır" }));
    await waitFor(() => expect(apiMocks.runCoverageBatch).toHaveBeenCalled());
    expect(apiMocks.runCoverageBatch.mock.calls[0][0].append).toBe(false);
  });
});

describe("OperationsQaPanel — HITL kuyruğu", () => {
  it("HITL listesini render eder ve onayı iletir", async () => {
    apiMocks.listHitlPending.mockResolvedValueOnce({
      pending: [
        {
          request_id: "req-1",
          action: "approve_landing",
          description: "Landing page hazır",
          payload: { url: "/preview" },
        },
      ],
    }).mockResolvedValueOnce({ pending: [] });
    apiMocks.respondHitl.mockResolvedValue({ ok: true });

    const user = userEvent.setup();
    render(<OperationsQaPanel />);

    expect(await screen.findByText("approve_landing")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Onayla" }));

    await waitFor(() => expect(apiMocks.respondHitl).toHaveBeenCalledWith("req-1", expect.objectContaining({
      approved: true,
      decided_by: "ops-qa-panel",
    })));
  });

  it("reddetme reasoning'i iletir", async () => {
    apiMocks.listHitlPending.mockResolvedValueOnce({
      pending: [
        { request_id: "req-2", action: "rollback", description: "Geri al", payload: {} },
      ],
    }).mockResolvedValueOnce({ pending: [] });
    apiMocks.respondHitl.mockResolvedValue({ ok: true });

    const user = userEvent.setup();
    render(<OperationsQaPanel />);

    expect(await screen.findByText("rollback")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reddet" }));

    await waitFor(() => {
      const [, body] = apiMocks.respondHitl.mock.calls[0];
      expect(body.approved).toBe(false);
      expect(body.rejection_reason).toMatch(/reddedildi/i);
    });
  });

  it("HITL yenileme butonu listHitlPending'i yeniden çağırır", async () => {
    const user = userEvent.setup();
    apiMocks.listHitlPending.mockResolvedValue({ pending: [] });
    render(<OperationsQaPanel />);

    await waitFor(() => expect(apiMocks.listHitlPending).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole("button", { name: "Yenile" }));
    await waitFor(() => expect(apiMocks.listHitlPending).toHaveBeenCalledTimes(2));
  });

  it("HITL listesi hatasını banner'a yansıtır", async () => {
    apiMocks.listHitlPending.mockRejectedValueOnce(new Error("HITL alınamadı"));
    render(<OperationsQaPanel />);
    expect(await screen.findByText("HITL alınamadı")).toBeInTheDocument();
  });
});

describe("OperationsQaPanel — WebSocket olay akışı", () => {
  it("gelen olayları listeye ekler ve temizleme butonu sıfırlar", async () => {
    const user = userEvent.setup();
    render(<OperationsQaPanel />);

    expect(webSocketOptions.onRoomEvent).toBeTypeOf("function");
    webSocketOptions.onRoomEvent({ id: "evt-1", source: "ops", kind: "status", content: "Hazır", ts: "2026-05-11T08:00:00Z" });

    expect(await screen.findByText("ops · status")).toBeInTheDocument();
    expect(screen.getByText("Hazır")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Temizle" }));
    expect(screen.getByText("Henüz durum olayı yok.")).toBeInTheDocument();
  });

  it("onStatus ve onError WS geri çağrıları durum bannerlarını günceller", async () => {
    render(<OperationsQaPanel />);
    webSocketOptions.onStatus("Bağlandı");
    webSocketOptions.onError("WS koptu");
    expect(await screen.findByText("Bağlandı")).toBeInTheDocument();
    expect(await screen.findByText("WS koptu")).toBeInTheDocument();
  });
});
