import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TenantAdminPanel } from "./TenantAdminPanel.jsx";

describe("TenantAdminPanel", () => {
  it("adds a tenant and clears the input", async () => {
    const user = userEvent.setup();
    render(<TenantAdminPanel />);

    const input = screen.getByLabelText("Yeni tenant adı");
    await user.type(input, "Helios Enerji");
    await user.click(screen.getByRole("button", { name: "Tenant Ekle" }));

    expect(screen.getByRole("heading", { name: "Helios Enerji" })).toBeInTheDocument();
    expect(input).toHaveValue("");
  });

  it("does not add tenant when input is blank/whitespace", async () => {
    const user = userEvent.setup();
    render(<TenantAdminPanel />);

    const initialCards = screen.getAllByRole("heading", { level: 3 }).length;
    const input = screen.getByLabelText("Yeni tenant adı");

    await user.type(input, "   ");
    await user.click(screen.getByRole("button", { name: "Tenant Ekle" }));

    expect(screen.getAllByRole("heading", { level: 3 })).toHaveLength(initialCards);
  });

  // GÜNCELLENEN TEST: Her iki toggle (değiştirme) yönünü de test eder
  it("toggles the tenant status label in both directions (active <-> paused)", async () => {
    const user = userEvent.setup();
    render(<TenantAdminPanel />);

    // --- 1. YÖN: Active -> Paused (True Dalı) ---
    // Acme Finans başlangıçta "active"dir, "Duraklat" butonuna tıklıyoruz.
    const pauseButtons = screen.getAllByRole("button", { name: "Duraklat" });
    await user.click(pauseButtons[0]);

    // Ekrandaki "Aktifleştir" butonu sayısı artmış olmalı (Başlangıçta sadece Nova Lojistik için vardı, şimdi Acme için de var)
    expect(screen.getAllByRole("button", { name: "Aktifleştir" })).toHaveLength(2);

    // --- 2. YÖN: Paused -> Active (False Dalı - Eksik Olan Satır 33 İçin) ---
    // Şimdi ekrandaki herhangi bir "Aktifleştir" butonuna tıklıyoruz.
    const activateButtons = screen.getAllByRole("button", { name: "Aktifleştir" });
    await user.click(activateButtons[0]);

    // Tıkladığımız tenant yeniden aktif olduğu için "Duraklat" butonlarının sayısı da doğru şekilde güncellenmiş olmalı.
    expect(screen.getAllByRole("button", { name: "Duraklat" })).toHaveLength(2);
  });
});