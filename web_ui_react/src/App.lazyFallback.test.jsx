import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import App from "./App.jsx";

vi.mock("./components/ChatPanel.jsx", () => ({ ChatPanel: () => <div>Chat Mock</div> }));
vi.mock("./components/P2PDialoguePanel.jsx", () => ({ P2PDialoguePanel: undefined }));

describe("App lazy panel fallback", () => {
  it("renders MissingLazyPanel hint when lazy module lacks the named export", async () => {
    render(
      <MemoryRouter initialEntries={["/p2p"]}>
        <App />
      </MemoryRouter>,
    );

    expect(
      await screen.findByText("Panel bileşeni yüklenemedi: P2PDialoguePanel"),
    ).toBeVisible();
  });
});
