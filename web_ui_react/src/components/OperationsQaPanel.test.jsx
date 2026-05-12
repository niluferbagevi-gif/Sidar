import React from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
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

async function renderOperationsQaPanel() {
  const view = render(<OperationsQaPanel />);
  await waitFor(() => expect(apiMocks.listHitlPending).toHaveBeenCalled());
  return view;
}

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
    await renderOperationsQaPanel();
    expect(screen.getByText("Poyraz & Coverage Kontrol Paneli")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Oda: ops:control/i })).toBeInTheDocument();
    await waitFor(() => expect(apiMocks.listHitlPending).toHaveBeenCalled());
  });

  it("WS durum chip'ini gösterir", async () => {
    wsState.status = "disconnected";
    await renderOperationsQaPanel();
    expect(screen.getByText("WS: disconnected")).toBeInTheDocument();
  });

  it("oda değiştirme butonu aktif odayı değiştirir", async () => {
    const user = userEvent.setup();
    await renderOperationsQaPanel();
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
    await renderOperationsQaPanel();

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
    await renderOperationsQaPanel();

    await user.click(screen.getByRole("button", { name: "Kopya üret" }));

    await waitFor(() => expect(apiMocks.generateCampaignCopy).toHaveBeenCalledTimes(1));
    const payload = apiMocks.generateCampaignCopy.mock.calls[0][0];
    expect(payload.channels).toEqual(["LinkedIn", "email"]);
    expect(payload.room_id).toBe("ops:control");
  });

  it("Coverage analizi formu analyzeCoverage çağırır", async () => {
    const user = userEvent.setup();
    apiMocks.analyzeCoverage.mockResolvedValue({ ok: true });
    await renderOperationsQaPanel();

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
    await renderOperationsQaPanel();

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
    await renderOperationsQaPanel();

    await user.click(screen.getByRole("button", { name: "Landing üret" }));

    expect(await screen.findByText("Landing patladı")).toBeInTheDocument();
    expect(await screen.findByText("Landing page başarısız.")).toBeInTheDocument();
  });
});

describe("OperationsQaPanel — form girdileri", () => {
  it("Landing form alanları kontrollü güncellenir", async () => {
    const user = userEvent.setup();
    apiMocks.generateLandingPage.mockResolvedValue({ ok: true });
    await renderOperationsQaPanel();
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
    await renderOperationsQaPanel();
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
    await renderOperationsQaPanel();

    expect(await screen.findByText("approve_landing")).toBeInTheDocument();
    expect(screen.getByText(/preview/)).toBeInTheDocument();
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
    await renderOperationsQaPanel();

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
    await renderOperationsQaPanel();

    await waitFor(() => expect(apiMocks.listHitlPending).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole("button", { name: "Yenile" }));
    await waitFor(() => expect(apiMocks.listHitlPending).toHaveBeenCalledTimes(2));
  });

  it("HITL listesi hatasını banner'a yansıtır", async () => {
    apiMocks.listHitlPending.mockRejectedValueOnce(new Error("HITL alınamadı"));
    await renderOperationsQaPanel();
    expect(await screen.findByText("HITL alınamadı")).toBeInTheDocument();
  });

  it("pending alanı eksik HITL yanıtını boş liste olarak işler", async () => {
    apiMocks.listHitlPending.mockResolvedValueOnce({});
    await renderOperationsQaPanel();
    expect(screen.getByText("Bekleyen HITL isteği yok.")).toBeInTheDocument();
  });

  it("payload alanı eksik HITL öğelerini boş JSON olarak render eder", async () => {
    apiMocks.listHitlPending.mockResolvedValueOnce({
      pending: [{ request_id: "req-empty-payload", action: "audit", description: "Kontrol" }],
    });

    await renderOperationsQaPanel();

    expect(await screen.findByText("audit")).toBeInTheDocument();
    expect(screen.getAllByText("{}")).toHaveLength(2);
  });
});

describe("OperationsQaPanel — WebSocket olay akışı", () => {
  it("gelen olayları listeye ekler ve temizleme butonu sıfırlar", async () => {
    const user = userEvent.setup();
    await renderOperationsQaPanel();

    expect(webSocketOptions.onRoomEvent).toBeTypeOf("function");
    act(() => {
      webSocketOptions.onRoomEvent({ id: "evt-1", source: "ops", kind: "status", content: "Hazır", ts: "2026-05-11T08:00:00Z" });
    });

    expect(await screen.findByText("ops · status")).toBeInTheDocument();
    expect(screen.getByText("Hazır")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Temizle" }));
    expect(screen.getByText("Henüz durum olayı yok.")).toBeInTheDocument();
  });

  it("eksik alanlı WS olayları için varsayılan başlık ve boş içerik üretir", async () => {
    await renderOperationsQaPanel();

    act(() => {
      webSocketOptions.onRoomEvent({ ts: "2026-05-11T09:00:00Z" });
    });

    expect(await screen.findByText("api · status")).toBeInTheDocument();
    expect(screen.getByText("2026-05-11T09:00:00Z")).toBeInTheDocument();
  });

  it("zaman damgası eksik WS olaylarını boş ts ile render eder", async () => {
    await renderOperationsQaPanel();

    act(() => {
      webSocketOptions.onRoomEvent({ id: "evt-no-ts", source: "ops", kind: "notice", content: "TS yok" });
    });

    expect(await screen.findByText("ops · notice")).toBeInTheDocument();
    expect(screen.getByText("TS yok")).toBeInTheDocument();
  });

  it("onStatus ve onError WS geri çağrıları durum bannerlarını günceller", async () => {
    await renderOperationsQaPanel();
    act(() => {
      webSocketOptions.onStatus("Bağlandı");
    });
    act(() => {
      webSocketOptions.onError("WS koptu");
    });
    expect(await screen.findByText("Bağlandı")).toBeInTheDocument();
    expect(await screen.findByText("WS koptu")).toBeInTheDocument();
  });
});

describe("OperationsQaPanel — Coverage form alanları", () => {
  it("Coverage analiz formu kontrollü güncellenir", async () => {
    const user = userEvent.setup();
    apiMocks.analyzeCoverage.mockResolvedValue({ ok: true });
    await renderOperationsQaPanel();
    const xmlInputs = screen.getAllByDisplayValue("coverage.xml");
    const rcInputs = screen.getAllByDisplayValue(".coveragerc");
    const limitInputs = screen.getAllByDisplayValue("10");
    await user.clear(xmlInputs[0]);
    await user.type(xmlInputs[0], "alt/coverage.xml");
    await user.clear(rcInputs[0]);
    await user.type(rcInputs[0], "alt/.coveragerc");
    await user.clear(limitInputs[0]);
    await user.type(limitInputs[0], "42");
    await user.click(screen.getByRole("button", { name: "Analiz et" }));
    await waitFor(() => expect(apiMocks.analyzeCoverage).toHaveBeenCalled());
    const payload = apiMocks.analyzeCoverage.mock.calls[0][0];
    expect(payload.coverage_xml).toBe("alt/coverage.xml");
    expect(payload.coveragerc).toBe("alt/.coveragerc");
    expect(payload.limit).toBe(42);
  });

  it("Coverage batch formu kontrollü güncellenir", async () => {
    const user = userEvent.setup();
    apiMocks.runCoverageBatch.mockResolvedValue({ ok: true });
    await renderOperationsQaPanel();
    const xmlInputs = screen.getAllByDisplayValue("coverage.xml");
    const limitInputs = screen.getAllByDisplayValue("5");
    const batchSizeInputs = screen.getAllByDisplayValue("1");
    await user.clear(xmlInputs[1]);
    await user.type(xmlInputs[1], "batch/coverage.xml");
    await user.clear(limitInputs[0]);
    await user.type(limitInputs[0], "7");
    await user.clear(batchSizeInputs[0]);
    await user.type(batchSizeInputs[0], "3");
    await user.click(screen.getByRole("button", { name: "Batch çalıştır" }));
    await waitFor(() => expect(apiMocks.runCoverageBatch).toHaveBeenCalled());
    const payload = apiMocks.runCoverageBatch.mock.calls[0][0];
    expect(payload.coverage_xml).toBe("batch/coverage.xml");
    expect(payload.limit).toBe(7);
    expect(payload.batch_size).toBe(3);
  });
});
