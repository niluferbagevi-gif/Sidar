import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TenantAdminPanel } from "./TenantAdminPanel.jsx";
import { fetchJson } from "../lib/api.js";

vi.mock("../lib/api.js", () => ({
  fetchJson: vi.fn(),
}));

const policiesPayload = {
  items: [
    {
      id: 1,
      user_id: "user-1",
      tenant_id: "acme",
      resource_type: "rag",
      resource_id: "*",
      action: "read",
      effect: "allow",
    },
  ],
};

const auditPayload = {
  items: [
    {
      id: 10,
      user_id: "user-1",
      tenant_id: "acme",
      action: "read",
      resource: "rag:*",
      allowed: true,
      timestamp: "2026-07-03T10:00:00Z",
    },
    {
      id: 11,
      user_id: "user-2",
      tenant_id: "acme",
      action: "manage",
      resource: "admin:*",
      allowed: false,
      timestamp: "2026-07-03T10:05:00Z",
    },
  ],
};

function mockFetchJson(url, options = {}) {
  if (url.startsWith("/admin/audit-logs")) return Promise.resolve(auditPayload);
  if (url.startsWith("/admin/policies/user-1") && !options.method) return Promise.resolve(policiesPayload);
  if (url === "/admin/policies" && options.method === "POST") return Promise.resolve(policiesPayload);
  return Promise.resolve({ items: [] });
}

describe("TenantAdminPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchJson.mockImplementation(mockFetchJson);
  });

  it("loads tenant audit logs from backend on initial render", async () => {
    render(<TenantAdminPanel />);

    expect(await screen.findByText("Audit Trail")).toBeInTheDocument();
    expect(await screen.findByText("rag:*")).toBeInTheDocument();
    expect(screen.getByText("admin:*")).toBeInTheDocument();
    expect(screen.getByText("İzinli audit").previousSibling).toHaveTextContent("1");
    expect(screen.getByText("Reddedilen audit").previousSibling).toHaveTextContent("1");
    expect(fetchJson).toHaveBeenCalledWith("/admin/audit-logs?tenant_id=default&limit=50");
  });

  it("lists policies for the selected user and tenant", async () => {
    const user = userEvent.setup();
    render(<TenantAdminPanel />);

    await user.clear(screen.getByLabelText("Tenant ID"));
    await user.type(screen.getByLabelText("Tenant ID"), "acme");
    await user.type(screen.getByLabelText("Kullanıcı ID"), "user-1");

    await waitFor(() => {
      expect(fetchJson).toHaveBeenCalledWith("/admin/policies/user-1?tenant_id=acme");
    });
    const policyCard = await screen.findByText("ALLOW · rag:*");
    expect(policyCard).toBeInTheDocument();
    expect(within(policyCard.closest(".policy-item")).getByText(/tenant:acme/)).toBeInTheDocument();
  });

  it("upserts a real RBAC policy through the admin policy API", async () => {
    const user = userEvent.setup();
    render(<TenantAdminPanel />);

    await user.clear(screen.getByLabelText("Tenant ID"));
    await user.type(screen.getByLabelText("Tenant ID"), "acme");
    await user.type(screen.getByLabelText("Kullanıcı ID"), "user-1");
    await user.click(screen.getByRole("button", { name: "Politikayı Kaydet" }));

    await waitFor(() => {
      expect(fetchJson).toHaveBeenCalledWith("/admin/policies", expect.objectContaining({ method: "POST" }));
    });
    const [, request] = fetchJson.mock.calls.find(([url]) => url === "/admin/policies");
    expect(JSON.parse(request.body)).toMatchObject({ user_id: "user-1", tenant_id: "acme", resource_type: "rag" });
    expect(await screen.findByText("acme tenant erişim politikası kaydedildi.")).toBeInTheDocument();
  });

  it("shows a controlled error banner when tenant data loading fails", async () => {
    fetchJson.mockRejectedValueOnce(new Error("audit API unavailable"));

    render(<TenantAdminPanel />);

    expect(await screen.findByRole("alert")).toHaveTextContent("audit API unavailable");
    expect(screen.getByRole("button", { name: "Yenile" })).not.toBeDisabled();
  });

  it("shows an empty-policy hint when the selected user has no tenant policies", async () => {
    const user = userEvent.setup();
    fetchJson.mockImplementation((url) => {
      if (url.startsWith("/admin/audit-logs")) return Promise.resolve({ items: [] });
      if (url.startsWith("/admin/policies/user-empty")) return Promise.resolve({ items: [] });
      return Promise.resolve({ items: [] });
    });

    render(<TenantAdminPanel />);

    await user.type(screen.getByLabelText("Kullanıcı ID"), "user-empty");

    expect(await screen.findByText("Bu kullanıcı/tenant için politika yok.")).toBeInTheDocument();
  });

  it("keeps invalid audit timestamps readable instead of formatting them", async () => {
    fetchJson.mockResolvedValueOnce({
      items: [
        {
          id: 42,
          user_id: "user-1",
          action: "read",
          resource: "rag:*",
          allowed: true,
          timestamp: "not-a-date",
        },
      ],
    });

    render(<TenantAdminPanel />);

    expect(await screen.findByText("not-a-date")).toBeInTheDocument();
  });

  it("validates user id before submitting a policy", async () => {
    render(<TenantAdminPanel />);

    await screen.findByText("Audit Trail");
    fireEvent.submit(screen.getByRole("button", { name: "Politikayı Kaydet" }).closest("form"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "RBAC politikası kaydetmek için kullanıcı ID zorunludur.",
    );
    expect(fetchJson).not.toHaveBeenCalledWith("/admin/policies", expect.anything());
  });

  it("shows submit errors without replacing existing policies", async () => {
    const user = userEvent.setup();
    fetchJson.mockImplementation((url, options = {}) => {
      if (url.startsWith("/admin/audit-logs")) return Promise.resolve(auditPayload);
      if (url.startsWith("/admin/policies/user-1") && !options.method) {
        return Promise.resolve(policiesPayload);
      }
      if (url === "/admin/policies" && options.method === "POST") {
        return Promise.reject(new Error("policy write failed"));
      }
      return Promise.resolve({ items: [] });
    });

    render(<TenantAdminPanel />);

    await user.clear(screen.getByLabelText("Tenant ID"));
    await user.type(screen.getByLabelText("Tenant ID"), "acme");
    await user.type(screen.getByLabelText("Kullanıcı ID"), "user-1");
    expect(await screen.findByText("ALLOW · rag:*")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Politikayı Kaydet" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("policy write failed");
    expect(screen.getByText("ALLOW · rag:*")).toBeInTheDocument();
  });

  it("rebuilds the audit query when the tenant changes", async () => {
    const user = userEvent.setup();
    render(<TenantAdminPanel />);

    await screen.findByText("Audit Trail");
    await user.clear(screen.getByLabelText("Tenant ID"));
    await user.type(screen.getByLabelText("Tenant ID"), "acme");

    await waitFor(() => {
      expect(fetchJson).toHaveBeenCalledWith("/admin/audit-logs?tenant_id=acme&limit=50");
    });
  });

  it("submits normalized select values including deny effect", async () => {
    const user = userEvent.setup();
    render(<TenantAdminPanel />);

    await user.clear(screen.getByLabelText("Tenant ID"));
    await user.type(screen.getByLabelText("Tenant ID"), "acme");
    await user.type(screen.getByLabelText("Kullanıcı ID"), "user-1");
    await user.selectOptions(screen.getByLabelText("Kaynak tipi"), "coverage");
    await user.selectOptions(screen.getByLabelText("Aksiyon"), "manage");
    await user.clear(screen.getByPlaceholderText("*"));
    await user.type(screen.getByPlaceholderText("*"), "repo-main");
    await user.selectOptions(screen.getByLabelText("Etki"), "deny");
    await user.click(screen.getByRole("button", { name: "Politikayı Kaydet" }));

    await waitFor(() => {
      expect(fetchJson).toHaveBeenCalledWith("/admin/policies", expect.objectContaining({ method: "POST" }));
    });
    const [, request] = fetchJson.mock.calls.find(([url]) => url === "/admin/policies");
    expect(JSON.parse(request.body)).toMatchObject({
      user_id: "user-1",
      tenant_id: "acme",
      resource_type: "coverage",
      resource_id: "repo-main",
      action: "manage",
      effect: "deny",
    });
  });

  it("disables the refresh button while tenant data is loading", async () => {
    let resolveAudit;
    fetchJson.mockImplementation((url) => {
      if (url.startsWith("/admin/audit-logs")) {
        return new Promise((resolve) => {
          resolveAudit = resolve;
        });
      }
      return Promise.resolve({ items: [] });
    });

    render(<TenantAdminPanel />);

    const refreshButton = screen.getByRole("button", { name: "Yükleniyor..." });
    expect(refreshButton).toBeDisabled();

    resolveAudit({ items: [] });

    expect(await screen.findByRole("button", { name: "Yenile" })).not.toBeDisabled();
  });

  it("renders multiple policies for the selected user", async () => {
    const user = userEvent.setup();
    fetchJson.mockImplementation((url, options = {}) => {
      if (url.startsWith("/admin/audit-logs")) return Promise.resolve({ items: [] });
      if (url.startsWith("/admin/policies/user-1") && !options.method) {
        return Promise.resolve({
          items: [
            { ...policiesPayload.items[0], id: 1, effect: "allow", resource_type: "rag", resource_id: "*", action: "read" },
            { ...policiesPayload.items[0], id: 2, effect: "deny", resource_type: "admin", resource_id: "settings", action: "manage" },
          ],
        });
      }
      return Promise.resolve({ items: [] });
    });

    render(<TenantAdminPanel />);

    await user.clear(screen.getByLabelText("Tenant ID"));
    await user.type(screen.getByLabelText("Tenant ID"), "acme");
    await user.type(screen.getByLabelText("Kullanıcı ID"), "user-1");

    expect(await screen.findByText("ALLOW · rag:*")).toBeInTheDocument();
    expect(screen.getByText("DENY · admin:settings")).toBeInTheDocument();
    expect(screen.getByText("RBAC politika").previousSibling).toHaveTextContent("2");
  });

  it("does not fetch policies until a current user id is present", async () => {
    render(<TenantAdminPanel />);

    await screen.findByText("Audit Trail");

    expect(fetchJson).toHaveBeenCalledWith("/admin/audit-logs?tenant_id=default&limit=50");
    expect(fetchJson.mock.calls.some(([url]) => url.startsWith("/admin/policies/"))).toBe(false);
    expect(screen.getByText("Politika listelemek için kullanıcı ID girin.")).toBeInTheDocument();
  });

  it("counts audit allowed and denied edge values from backend payloads", async () => {
    fetchJson.mockResolvedValueOnce({
      items: [
        { id: 1, user_id: "user-1", action: "read", resource: "rag:*", allowed: false, timestamp: "" },
        { id: 2, user_id: "user-2", action: "write", resource: "github:repo", allowed: false, timestamp: "" },
        { id: 3, user_id: "user-3", action: "execute", resource: "agents:*", timestamp: "" },
      ],
    });

    render(<TenantAdminPanel />);

    expect(await screen.findByText("rag:*")).toBeInTheDocument();
    expect(screen.getByText("İzinli audit").previousSibling).toHaveTextContent("0");
    expect(screen.getByText("Reddedilen audit").previousSibling).toHaveTextContent("3");
    expect(screen.getAllByText("Red", { selector: ".status-pill" })).toHaveLength(3);
    expect(screen.queryByText("İzin", { selector: ".status-pill" })).not.toBeInTheDocument();
  });


  it("falls back to empty arrays when audit and policy responses omit items", async () => {
    const user = userEvent.setup();
    fetchJson.mockImplementation((url, options = {}) => {
      if (url.startsWith("/admin/audit-logs")) return Promise.resolve({});
      if (url.startsWith("/admin/policies/user-1") && !options.method) return Promise.resolve({});
      if (url === "/admin/policies" && options.method === "POST") return Promise.resolve({});
      return Promise.resolve({});
    });

    render(<TenantAdminPanel />);

    await user.clear(screen.getByLabelText("Tenant ID"));
    await user.type(screen.getByLabelText("Tenant ID"), "acme");
    await user.type(screen.getByLabelText("Kullanıcı ID"), "user-1");
    expect(await screen.findByText("Bu kullanıcı/tenant için politika yok.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Politikayı Kaydet" }));

    expect(await screen.findByText("acme tenant erişim politikası kaydedildi.")).toBeInTheDocument();
    expect(screen.getByText("RBAC politika").previousSibling).toHaveTextContent("0");
  });

  it("renders anonymous audit users when backend user id is missing", async () => {
    fetchJson.mockResolvedValueOnce({
      items: [
        { id: 1, action: "read", resource: "rag:*", allowed: true, timestamp: "" },
      ],
    });

    render(<TenantAdminPanel />);

    expect(await screen.findByText("anonim")).toBeInTheDocument();
    expect(screen.getByText("İzinli audit").previousSibling).toHaveTextContent("1");
  });

  it("normalizes blank tenant and resource values to safe defaults before submit", async () => {
    const user = userEvent.setup();
    render(<TenantAdminPanel />);

    await screen.findByText("Audit Trail");
    await user.clear(screen.getByLabelText("Tenant ID"));
    await user.type(screen.getByLabelText("Kullanıcı ID"), "  user-1  ");
    await user.clear(screen.getByPlaceholderText("*"));
    fireEvent.submit(screen.getByRole("button", { name: "Politikayı Kaydet" }).closest("form"));

    await waitFor(() => {
      expect(fetchJson).toHaveBeenCalledWith("/admin/policies", expect.objectContaining({ method: "POST" }));
    });
    const [, request] = fetchJson.mock.calls.find(([url]) => url === "/admin/policies");
    expect(JSON.parse(request.body)).toMatchObject({
      user_id: "user-1",
      tenant_id: "default",
      resource_id: "*",
      resource_type: "rag",
      action: "read",
      effect: "allow",
    });
  });

});
