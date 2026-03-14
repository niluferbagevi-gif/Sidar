const $ = (id) => document.getElementById(id);
const status = $("status");
const card = $("wizard-card");

const getPayload = () => {
  const mode = $("mode").value;
  return {
    mode,
    provider: $("provider").value,
    level: $("level").value,
    log: $("log").value,
    extra: {
      host: $("host").value,
      port: $("port").value,
      model: $("model").value,
    },
  };
};

const setStatus = (text, cls = "") => {
  status.className = `status-panel ${cls}`.trim();
  status.textContent = text;
};

$("btn-preflight").addEventListener("click", async () => {
  const { provider } = getPayload();
  setStatus("Preflight çalıştırılıyor...");
  gsap.fromTo(card, { y: 0 }, { y: -6, yoyo: true, repeat: 1, duration: 0.2 });

  try {
    const result = await eel.run_preflight(provider)();
    if (result.ok) {
      setStatus(`✅ Preflight tamamlandı. Sağlayıcı: ${result.provider}`, "success");
      return;
    }
    setStatus("⚠️ Preflight başarısız döndü.", "error");
  } catch (err) {
    setStatus(`❌ Preflight hatası: ${err}`, "error");
  }
});

$("btn-launch").addEventListener("click", async () => {
  const { mode, provider, level, log, extra } = getPayload();
  setStatus("Sidar başlatılıyor...");

  const tl = gsap.timeline();
  tl.to(".wizard-card", { opacity: 0.35, y: -12, duration: 0.35 })
    .to(".wizard-card", { opacity: 1, y: 0, duration: 0.3 });

  try {
    const result = await eel.start_sidar_from_gui(mode, provider, level, log, extra)();
    if (result.ok) {
      setStatus(`🚀 Başarılı. Çıkış kodu: ${result.return_code}\nKomut: ${result.command.join(" ")}`, "success");
      return;
    }
    setStatus(`❌ Başlatma başarısız. Çıkış kodu: ${result.return_code}`, "error");
  } catch (err) {
    setStatus(`❌ Başlatma hatası: ${err}`, "error");
  }
});
