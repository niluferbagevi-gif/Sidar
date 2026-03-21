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

  it("toggles the tenant status label", async () => {
    const user = userEvent.setup();
    render(<TenantAdminPanel />);

    await user.click(screen.getAllByRole("button", { name: "Duraklat" })[0]);

    expect(screen.getByText("Durum:", { exact: false })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Aktifleştir" })).toBeInTheDocument();
  });
});