import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AgentManagerPanel } from "./AgentManagerPanel.jsx";

vi.mock("../lib/api.js", async () => {
  const actual = await vi.importActual("../lib/api.js");
  return {
    ...actual,
    buildAuthHeaders: vi.fn(() => ({ Authorization: "Bearer test-token" })),
  };
});

describe("AgentManagerPanel", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    global.fetch = vi.fn();
  });

  it("shows a validation error when no python file is selected", async () => {
    const { container } = render(<AgentManagerPanel />);
    fireEvent.submit(screen.getByRole("button", { name: "Ajanı Kaydet" }).closest("form"));

    expect(screen.getByText("Lütfen bir Python ajan dosyası seçin.")).toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("renders panel as accessible region", () => {
    render(<AgentManagerPanel />);
    expect(screen.getByRole("region", { name: /agent manager paneli/i })).toBeInTheDocument();
  });

  it("submits the selected plugin file and renders the success preview", async () => {
    const user = userEvent.setup();
    global.fetch.mockResolvedValue({
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

    fireEvent.submit(screen.getByRole("button", { name: "Ajanı Kaydet" }).closest("form"));

    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
    const [url, options] = global.fetch.mock.calls[0];
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
    global.fetch.mockResolvedValue({
      ok: false,
      json: async () => ({ detail: "Agent kaydı başarısız" }),
    });

    render(<AgentManagerPanel />);
    await user.upload(screen.getByLabelText(/Python dosyası/), new File(["print('bad')"], "bad_agent.py", { type: "text/x-python" }));
    await user.type(screen.getByPlaceholderText("security-auditor"), "security-auditor");

    fireEvent.submit(screen.getByRole("button", { name: "Ajanı Kaydet" }).closest("form"));

    expect(await screen.findByText("Agent kaydı başarısız")).toBeInTheDocument();
  });

  it("falls back to generic backend error field and toggles submitting state", async () => {
    const user = userEvent.setup();
    let resolveResponse;
    global.fetch.mockReturnValue(
      new Promise((resolve) => {
        resolveResponse = resolve;
      }),
    );

    render(<AgentManagerPanel />);
    await user.upload(screen.getByLabelText(/Python dosyası/), new File(["print('bad')"], "bad_agent.py", { type: "text/x-python" }));
    fireEvent.submit(screen.getByRole("button", { name: "Ajanı Kaydet" }).closest("form"));

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
    global.fetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        agent: { role_name: "security-auditor", version: "1.0.0" },
      }),
    });

    render(<AgentManagerPanel />);
    await user.upload(screen.getByLabelText(/Python dosyası/), new File(["print('ok')"], "security_agent.py", { type: "text/x-python" }));
    await user.clear(screen.getByPlaceholderText("1.0.0"));

    fireEvent.submit(screen.getByRole("button", { name: "Ajanı Kaydet" }).closest("form"));

    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
    const [, options] = global.fetch.mock.calls[0];
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
    global.fetch.mockResolvedValue({
      ok: false,
      json: async () => ({}),
    });

    render(<AgentManagerPanel />);
    await user.upload(screen.getByLabelText(/Python dosyası/), new File(["print('ok')"], "test.py", { type: "text/x-python" }));

    fireEvent.submit(screen.getByRole("button", { name: "Ajanı Kaydet" }).closest("form"));

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
