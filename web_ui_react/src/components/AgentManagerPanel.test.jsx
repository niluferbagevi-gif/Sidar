import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
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
    const user = userEvent.setup();
    render(<AgentManagerPanel />);

    await user.click(screen.getByRole("button", { name: "Ajanı Kaydet" }));

    expect(screen.getByText("Lütfen bir Python ajan dosyası seçin.")).toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("submits the selected plugin file and renders the success preview", async () => {
    const user = userEvent.setup();
    global.fetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        agent: { role_name: "security-auditor", version: "2.0.0", capabilities: ["security_audit"] },
      }),
    });

    render(<AgentManagerPanel />);

    await user.upload(screen.getByLabelText(/Python dosyası/), new File(["print('ok')"], "security_agent.py", { type: "text/x-python" }));
    await user.type(screen.getByPlaceholderText("security-auditor"), "security-auditor");
    await user.type(screen.getByPlaceholderText("MyCustomAgent"), "SecurityAgent");
    await user.type(screen.getByPlaceholderText("security_audit, quality_check"), "security_audit, quality_check");
    await user.type(screen.getByPlaceholderText("Plugin ajanının kısa açıklaması"), "Denetim ajanı");
    await user.clear(screen.getByPlaceholderText("1.0.0"));
    await user.type(screen.getByPlaceholderText("1.0.0"), "2.0.0");

    await user.click(screen.getByRole("button", { name: "Ajanı Kaydet" }));

    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
    const [url, options] = global.fetch.mock.calls[0];
    expect(url).toBe("/api/agents/register-file");
    expect(options.method).toBe("POST");
    expect(options.headers).toEqual({ Authorization: "Bearer test-token" });
    expect(options.body).toBeInstanceOf(FormData);
    expect(screen.getByText(/security-auditor ajanı yüklendi/)).toBeInTheDocument();
    expect(screen.getByText(/"version": "2.0.0"/)).toBeInTheDocument();
    expect(screen.getByText(/Seçilmedi/)).toBeInTheDocument();
  });
});
