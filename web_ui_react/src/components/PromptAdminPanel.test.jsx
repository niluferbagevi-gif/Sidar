import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PromptAdminPanel } from "./PromptAdminPanel.jsx";

const fetchJson = vi.fn();

vi.mock("../lib/api.js", () => ({ fetchJson }));

describe("PromptAdminPanel", () => {
  beforeEach(() => {
    fetchJson.mockReset();
  });

  it("loads prompts and submits a new prompt revision", async () => {
    const user = userEvent.setup();
    fetchJson
      .mockResolvedValueOnce({
        items: [{ id: "p1", role_name: "system", is_active: true, version: 3, prompt_text: "Mevcut prompt", updated_at: "2025-01-01" }],
      })
      .mockResolvedValueOnce({ ok: true })
      .mockResolvedValueOnce({
        items: [{ id: "p2", role_name: "system", is_active: true, version: 4, prompt_text: "Yeni prompt", updated_at: "2025-01-02" }],
      });

    render(<PromptAdminPanel />);

    expect(await screen.findByText("system")).toBeInTheDocument();
    await user.clear(screen.getByPlaceholderText("Yeni sistem promptu"));
    await user.type(screen.getByPlaceholderText("Yeni sistem promptu"), "Yeni prompt metni");
    await user.click(screen.getByRole("button", { name: "Kaydet" }));

    await waitFor(() => expect(fetchJson).toHaveBeenCalledWith("/admin/prompts", expect.objectContaining({ method: "POST" })));
    expect(screen.getByText("Prompt kaydedildi.")).toBeInTheDocument();
  });
});
