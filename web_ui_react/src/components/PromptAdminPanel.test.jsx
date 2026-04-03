import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PromptAdminPanel } from "./PromptAdminPanel.jsx";

const { fetchJson } = vi.hoisted(() => ({ fetchJson: vi.fn() }));

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
    const roleInput = screen.getByLabelText(/Rol adı/i);
    await user.clear(roleInput);
    await user.type(roleInput, "test_rol_adi");
    await user.clear(screen.getByPlaceholderText("Yeni sistem promptu"));
    await user.type(screen.getByPlaceholderText("Yeni sistem promptu"), "Yeni prompt metni");
    await user.click(screen.getByRole("button", { name: "Kaydet" }));

    await waitFor(() => expect(fetchJson).toHaveBeenCalledWith("/admin/prompts", expect.objectContaining({ method: "POST" })));
    expect(screen.getByText("Prompt kaydedildi.")).toBeInTheDocument();
  });

  it("shows load and submit errors when API fails", async () => {
    const user = userEvent.setup();
    fetchJson.mockImplementation(async (url, options) => {
      if (url.startsWith("/admin/prompts?role_name")) {
        throw new Error("Liste alınamadı");
      }
      if (url === "/admin/prompts" && options?.method === "POST") {
        throw new Error("Kaydetme hatası");
      }
      return { items: [] };
    });

    render(<PromptAdminPanel />);

    expect(await screen.findByText("Liste alınamadı")).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText("Yeni sistem promptu"), "bozuk payload");
    await user.click(screen.getByRole("button", { name: "Kaydet" }));

    expect(await screen.findByText("Kaydetme hatası")).toBeInTheDocument();
  });

  it("activates prompt versions and surfaces activation errors", async () => {
    const user = userEvent.setup();
    let activateCount = 0;
    fetchJson.mockImplementation(async (url, options) => {
      if (url.startsWith("/admin/prompts?role_name")) {
        return {
          items: [
            { id: "p-active", role_name: "system", is_active: true, version: 3, prompt_text: "Aktif", updated_at: "2025-01-01" },
            { id: "p-passive", role_name: "system", is_active: false, version: 4, prompt_text: "Pasif", updated_at: "2025-01-02" },
          ],
        };
      }
      if (url === "/admin/prompts/activate" && options?.method === "POST") {
        activateCount += 1;
        if (activateCount === 1) {
          return { version: 4 };
        }
        throw new Error("Aktifleştirme başarısız");
      }
      return { items: [] };
    });

    render(<PromptAdminPanel />);

    expect(await screen.findByText("Pasif")).toBeInTheDocument();
    const activateButtons = screen.getAllByRole("button", { name: "Aktif Yap" });
    await user.click(activateButtons[0]);
    expect(await screen.findByText("Aktif prompt sürümü v4 olarak güncellendi.")).toBeInTheDocument();

    const activateButtonsAfterRefresh = screen.getAllByRole("button", { name: "Aktif Yap" });
    await user.click(activateButtonsAfterRefresh[0]);
    expect(await screen.findByText("Aktifleştirme başarısız")).toBeInTheDocument();
  });

  it("updates filter, refreshes list and toggles activate checkbox", async () => {
    const user = userEvent.setup();
    fetchJson
      .mockResolvedValueOnce({ items: [] })
      .mockResolvedValueOnce({ items: [] });

    render(<PromptAdminPanel />);

    expect(await screen.findByText("Kayıt bulunamadı.")).toBeInTheDocument();
    const filterInput = screen.getByLabelText("role_name filtresi");
    await user.clear(filterInput);
    await user.type(filterInput, "reviewer");
    await user.click(screen.getByRole("button", { name: "Yenile" }));

    await waitFor(() => {
      expect(fetchJson).toHaveBeenLastCalledWith("/admin/prompts?role_name=reviewer");
    });

    const activateCheckbox = screen.getByRole("checkbox", { name: "Kaydeder kaydetmez aktif yap" });
    expect(activateCheckbox).toBeChecked();
    await user.click(activateCheckbox);
    expect(activateCheckbox).not.toBeChecked();
  });

  it("falls back to an empty list when API response has no items field", async () => {
    fetchJson.mockResolvedValueOnce({});

    render(<PromptAdminPanel />);

    expect(await screen.findByText("Kayıt bulunamadı.")).toBeInTheDocument();
    expect(screen.queryAllByRole("article")).toHaveLength(0);
  });

  it("truncates long prompt text with ellipsis in the list", async () => {
    const longPrompt = "a".repeat(225);
    const truncated = `${"a".repeat(220)}…`;

    fetchJson.mockResolvedValueOnce({
      items: [
        {
          id: "p-long",
          role_name: "system",
          is_active: true,
          version: 9,
          prompt_text: longPrompt,
          updated_at: "2026-01-01",
        },
      ],
    });

    render(<PromptAdminPanel />);

    expect(await screen.findByText(truncated)).toBeInTheDocument();
    expect(screen.queryByText(longPrompt)).not.toBeInTheDocument();
  });

});