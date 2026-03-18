import React, { useCallback, useState } from "react";

const INITIAL_TENANTS = [
  { id: "t-acme", name: "Acme Finans", plan: "Enterprise", agentQuota: 42, status: "active" },
  { id: "t-orion", name: "Orion Savunma", plan: "Business", agentQuota: 18, status: "active" },
  { id: "t-nova", name: "Nova Lojistik", plan: "Starter", agentQuota: 8, status: "paused" },
];

export function TenantAdminPanel() {
  const [tenants, setTenants] = useState(INITIAL_TENANTS);
  const [name, setName] = useState("");

  const addTenant = useCallback(() => {
    const normalized = name.trim();
    if (!normalized) return;
    setTenants((prev) => [
      {
        id: `t-${normalized.toLowerCase().replace(/\s+/g, "-")}`,
        name: normalized,
        plan: "Starter",
        agentQuota: 5,
        status: "active",
      },
      ...prev,
    ]);
    setName("");
  }, [name]);

  const toggleStatus = useCallback((tenantId) => {
    setTenants((prev) =>
      prev.map((item) =>
        item.id === tenantId
          ? { ...item, status: item.status === "active" ? "paused" : "active" }
          : item,
      ),
    );
  }, []);

  return (
    <section className="panel">
      <h2>Tenant Yönetim Paneli</h2>
      <p className="panel__hint">Örnek tenant kartları ile çok kiracılı operasyon akışını gözlemleyin.</p>
      <div className="tenant-form">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Yeni tenant adı"
          aria-label="Yeni tenant adı"
        />
        <button onClick={addTenant}>Tenant Ekle</button>
      </div>
      <div className="tenant-grid">
        {tenants.map((tenant) => (
          <article key={tenant.id} className="tenant-card">
            <h3>{tenant.name}</h3>
            <p>Plan: {tenant.plan}</p>
            <p>Ajan kotası: {tenant.agentQuota}</p>
            <p>Durum: <strong>{tenant.status === "active" ? "Aktif" : "Duraklatıldı"}</strong></p>
            <button onClick={() => toggleStatus(tenant.id)}>
              {tenant.status === "active" ? "Duraklat" : "Aktifleştir"}
            </button>
          </article>
        ))}
      </div>
    </section>
  );
}