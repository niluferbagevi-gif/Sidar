const selections = {
    mode: null,
    provider: null,
    level: null,
    log_level: "info",
};

let currentStep = 1;

function animateStepTransition(outgoingId, incomingId) {
    gsap.to(outgoingId, {
        x: -80,
        opacity: 0,
        duration: 0.35,
        onComplete: () => {
            document.querySelector(outgoingId).style.display = "none";
            gsap.fromTo(
                incomingId,
                { x: 80, opacity: 0, display: "block" },
                { x: 0, opacity: 1, duration: 0.45 }
            );
        },
    });
}

function selectOption(category, value) {
    selections[category] = value;

    const outgoing = `#step-${currentStep}`;
    currentStep += 1;

    if (currentStep > 3) {
        animateStepTransition(outgoing, "#step-loading");
        launchSidar();
        return;
    }

    const incoming = `#step-${currentStep}`;
    animateStepTransition(outgoing, incoming);
}

async function launchSidar() {
    const statusText = document.getElementById("status-text");

    gsap.to(".pulsate", { opacity: 0.4, repeat: -1, yoyo: true, duration: 0.75 });

    try {
        const response = await eel.start_sidar(
            selections.mode,
            selections.provider,
            selections.level,
            selections.log_level
        )();

        if (response.status === "success") {
            statusText.textContent = "Başarılı! Sidar çalıştırıldı, pencereyi kapatabilirsiniz.";
            statusText.style.color = "#10b981";
            return;
        }

        statusText.textContent = `Hata: ${response.message}`;
        statusText.style.color = "#ef4444";
    } catch (error) {
        statusText.textContent = `Bağlantı hatası: ${error}`;
        statusText.style.color = "#ef4444";
    }
}
