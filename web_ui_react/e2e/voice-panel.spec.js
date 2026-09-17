import { expect, test } from "@playwright/test";
import { openChatWithToken } from "./support/chatSession.js";
import { startMockSidarBackend } from "./support/mockSidarBackend.js";
import { startTestViteServer } from "./support/testViteServer.js";

async function installVoiceBrowserMocks(page) {
  await page.addInitScript(() => {
    class FakeMediaRecorder extends EventTarget {
      static isTypeSupported() {
        return true;
      }

      constructor() {
        super();
        this.state = "inactive";
      }

      start() {
        this.state = "recording";
      }

      stop() {
        this.state = "inactive";
      }

      requestData() {
        const blob = new Blob([new Uint8Array([1, 2, 3, 4])], { type: "audio/webm" });
        this.ondataavailable?.({ data: blob });
      }
    }

    class FakeAudioContext {
      createMediaStreamSource() {
        return { connect() {} };
      }

      createAnalyser() {
        let calls = 0;
        return {
          fftSize: 2048,
          smoothingTimeConstant: 0.82,
          getByteTimeDomainData(frame) {
            calls += 1;
            const value = calls < 4 ? 155 : 128;
            frame.fill(value);
          },
        };
      }

      close() {
        return Promise.resolve();
      }
    }

    // Plain `navigator.mediaDevices = {...}` silently no-ops in Chromium:
    // `mediaDevices` is a getter-only accessor on Navigator.prototype with no
    // setter, and this init script runs as a non-strict classic script, so
    // the assignment fails without throwing and every read keeps returning
    // the real native object -- the app then calls the real getUserMedia,
    // which rejects with "Requested device not found" in a headless/CI
    // browser with no camera/mic device, and the whole voice flow never gets
    // past that catch block. Object.defineProperty actually shadows the
    // accessor.
    Object.defineProperty(navigator, "mediaDevices", {
      value: {
        getUserMedia: () => Promise.resolve({
          getTracks: () => [{ stop() {} }],
        }),
      },
      configurable: true,
      writable: true,
    });
    window.MediaRecorder = FakeMediaRecorder;
    window.AudioContext = FakeAudioContext;
  });
}

test.describe("Voice assistant panel e2e", () => {
  test.describe.configure({ mode: "serial" });

  let backend;
  let frontend;

  test.beforeAll(async () => {
    backend = await startMockSidarBackend();
    frontend = await startTestViteServer({ backendUrl: backend.url });
  });

  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await page.addInitScript(() => localStorage.clear());
    await installVoiceBrowserMocks(page);
    await openChatWithToken(page, frontend.url);
  });

  test.afterAll(async () => {
    await frontend?.close();
    await backend?.close();
  });

  test("mikrofon başlatıldığında voice websocket transcript ve durum günceller", async ({ page }) => {
    await expect(page.getByRole("heading", { name: "Duplex Ses Deneyimi" })).toBeVisible();

    await page.getByRole("button", { name: "🎙 Mikrofonu Başlat" }).click();

    // "Mock sesli komut" also lands in the chat feed once the assistant
    // replies, so scope this to the "Son transcript" readout the test
    // actually means to assert on -- a bare getByText matches both and
    // trips Playwright's strict-mode ambiguity check.
    await expect(page.locator(".voice-panel__value").getByText("Mock sesli komut")).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText(/Voice durum: processed|Mikrofon açık/)).toBeVisible();

    await page.getByRole("button", { name: "■ Mikrofona Ara Ver" }).click();
    await expect(page.getByText("Mikrofon beklemede. Duplex konuşma için hazır.")).toBeVisible();
  });
});
