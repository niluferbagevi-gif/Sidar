import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AgentManagerPanel } from "./AgentManagerPanel.js";

vi.mock("../lib/api.js", async () => {
  const actual = await vi.importActual("../lib/api.js");
  return {
    ...actual,
    buildAuthHeaders: vi.fn(() => ({ Authorization: "Bearer test-token" })),
  };
});

// A fresh fetch mock per test; typed loosely because tests feed partial Response shapes.
let fetchMock: ReturnType<typeof vi.fn>;

function submitForm() {
  fireEvent.submit(
    screen.getByRole("button", { name: "Ajanı Kaydet" }).closest("form") as HTMLFormElement,
  );
}

describe("AgentManagerPanel", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
  });

  it("shows a validation error when no python file is selected", async () => {
    render(<AgentManagerPanel />);
    submitForm();

    expect(screen.getByText("Lütfen bir Python ajan dosyası seçin.")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("renders panel as accessible region", () => {
    render(<AgentManagerPanel />);
    expect(screen.getByRole("region", { name: /agent manager paneli/i })).toBeInTheDocument();
  });

  it("submits the selected plugin file and renders the success preview", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        agent: { role_name: "security-auditor", version: "2.0.0", capabilities: ["security_audit"] },
      }),
    });

    const { container } = render(<AgentManagerPanel />);

    await user.upload(screen.getByLabelText(/Python dosyası/), new File(["print('ok')"], "security_agent.py", { type: "text/x-python" }));
    await user.type(screen.getByPlaceholderText("security-auditor"), "security-auditor");
    await user.type(screen.getByPlaceholderText("MyCustomAgent"), "SecurityAgent");
    await user.type(screen.getByPlaceholderText("security_audit, quality_check"), "security_audit, quality_check");
    await user.type(screen.getByPlaceholderText("Plugin ajanının kısa açıklaması"), "Denetim ajanı");
    await user.clear(screen.getByPlaceholderText("1.0.0"));
    await user.type(screen.getByPlaceholderText("1.0.0"), "2.0.0");

    submitForm();

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/agents/register-file");
    expect(options.method).toBe("POST");
    expect(options.headers).toEqual({ Authorization: "Bearer test-token" });
    expect(options.body).toBeInstanceOf(FormData);
    expect(container.querySelector(".banner--success")).toHaveTextContent("security-auditor ajanı yüklendi. Sürüm: 2.0.0");
    expect(screen.getByText(/"version": "2.0.0"/)).toBeInTheDocument();
    expect(screen.getByText(/Seçilmedi/)).toBeInTheDocument();
  });

  it("renders backend error banner when registration fails", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValue({
      ok: false,
      json: async () => ({ detail: "Agent kaydı başarısız" }),
    });

    render(<AgentManagerPanel />);
    await user.upload(screen.getByLabelText(/Python dosyası/), new File(["print('bad')"], "bad_agent.py", { type: "text/x-python" }));
    await user.type(screen.getByPlaceholderText("security-auditor"), "security-auditor");

    submitForm();

    expect(await screen.findByText("Agent kaydı başarısız")).toBeInTheDocument();
  });

  it("falls back to generic backend error field and toggles submitting state", async () => {
    const user = userEvent.setup();
    let resolveResponse: (value: unknown) => void = () => {};
    fetchMock.mockReturnValue(
      new Promise((resolve) => {
        resolveResponse = resolve;
      }),
    );

    render(<AgentManagerPanel />);
    await user.upload(screen.getByLabelText(/Python dosyası/), new File(["print('bad')"], "bad_agent.py", { type: "text/x-python" }));
    submitForm();

    expect(screen.getByRole("button", { name: "Yükleniyor…" })).toBeDisabled();

    resolveResponse({
      ok: false,
      json: async () => ({ error: "Upload blocked" }),
    });

    expect(await screen.findByText("Upload blocked")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ajanı Kaydet" })).toBeEnabled();
  });


  it("uses default version in payload when version input is blank", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        agent: { role_name: "security-auditor", version: "1.0.0" },
      }),
    });

    render(<AgentManagerPanel />);
    await user.upload(screen.getByLabelText(/Python dosyası/), new File(["print('ok')"], "security_agent.py", { type: "text/x-python" }));
    await user.clear(screen.getByPlaceholderText("1.0.0"));

    submitForm();

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [, options] = fetchMock.mock.calls[0];
    expect(options.body).toBeInstanceOf(FormData);
    expect(options.body.get("version")).toBe("1.0.0");
  });

  it("sets file back to null when file input change event has no files", () => {
    render(<AgentManagerPanel />);

    const fileInput = screen.getByLabelText(/Python dosyası/);
    fireEvent.change(fileInput, { target: { files: [new File(["print('ok')"], "my_agent.py", { type: "text/x-python" })] } });
    expect(screen.getByText("my_agent")).toBeInTheDocument();

    fireEvent.change(fileInput, { target: { files: [] } });
    expect(screen.getByText("Seçilmedi")).toBeInTheDocument();
    expect(screen.getByText("Otomatik")).toBeInTheDocument();
  });
  it("uses default error message when detail and error are missing", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValue({
      ok: false,
      json: async () => ({}),
    });

    render(<AgentManagerPanel />);
    await user.upload(screen.getByLabelText(/Python dosyası/), new File(["print('ok')"], "test.py", { type: "text/x-python" }));

    submitForm();

    expect(await screen.findByText("Ajan yüklenemedi")).toBeInTheDocument();
  });

  it("uses default error message when the backend error payload is null", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValue({
      ok: false,
      json: async () => null,
    });

    render(<AgentManagerPanel />);
    await user.upload(
      screen.getByLabelText(/Python dosyası/),
      new File(["print('ok')"], "test.py", { type: "text/x-python" }),
    );
    submitForm();

    expect(await screen.findByText("Ajan yüklenemedi")).toBeInTheDocument();
  });

  it("rejects malformed successful registration responses", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ agent: { version: 1 } }) });

    render(<AgentManagerPanel />);
    await user.upload(
      screen.getByLabelText(/Python dosyası/),
      new File(["print('ok')"], "test.py", { type: "text/x-python" }),
    );
    submitForm();

    expect(await screen.findByText("Ajan kayıt cevabı geçersiz")).toBeInTheDocument();
  });

  it.each([
    ["missing agent object", {}],
    ["non-object agent", { agent: null }],
    ["non-array capabilities", { agent: { role_name: "invalid", version: "1", capabilities: "audit" } }],
    ["non-string capability", { agent: { role_name: "invalid", version: "1", capabilities: [1] } }],
  ])("rejects %s in a successful registration payload", async (_label, responsePayload) => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValue({ ok: true, json: async () => responsePayload });

    render(<AgentManagerPanel />);
    await user.upload(
      screen.getByLabelText(/Python dosyası/),
      new File(["print('ok')"], "test.py", { type: "text/x-python" }),
    );
    submitForm();

    expect(await screen.findByText("Ajan kayıt cevabı geçersiz")).toBeInTheDocument();
  });

  it("normalizes non-Error request failures", async () => {
    const user = userEvent.setup();
    fetchMock.mockRejectedValue("network failure");

    render(<AgentManagerPanel />);
    await user.upload(
      screen.getByLabelText(/Python dosyası/),
      new File(["print('ok')"], "test.py", { type: "text/x-python" }),
    );
    submitForm();

    expect(await screen.findByText("Ajan yüklenemedi")).toBeInTheDocument();
  });

  it("displays auto-generated role name from file if role name is omitted", async () => {
    const user = userEvent.setup();
    render(<AgentManagerPanel />);

    expect(screen.getByText("Otomatik")).toBeInTheDocument();

    await user.upload(screen.getByLabelText(/Python dosyası/), new File(["print('ok')"], "my_agent.py", { type: "text/x-python" }));

    expect(screen.getByText("my_agent")).toBeInTheDocument();
  });
});
