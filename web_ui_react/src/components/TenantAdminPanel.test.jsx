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

  it("toggles the tenant status label", async () => {
    const user = userEvent.setup();
    render(<TenantAdminPanel />);

    await user.click(screen.getAllByRole("button", { name: "Duraklat" })[0]);

    expect(screen.getAllByText("Durum:", { exact: false }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: "Aktifleştir" }).length).toBeGreaterThan(0);
  });
});
