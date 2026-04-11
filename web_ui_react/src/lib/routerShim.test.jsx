import React, { useContext } from "react";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  BrowserRouter,
  MemoryRouter,
  Route,
  Routes,
  Navigate,
  NavLink,
} from "./routerShim.jsx";

// ─────────────────────────────────────────────────────────
// Yardımcılar
// ─────────────────────────────────────────────────────────

/** Belirtilen path ile BrowserRouter render eder. */
function renderWithRouter(ui, initialPath = "/") {
  window.history.replaceState({}, "", initialPath);
  return render(<BrowserRouter>{ui}</BrowserRouter>);
}

/** RouterContext değerini okuyan test bileşeni. */
const RouterContextConsumer = ({ onValue }) => {
  // BrowserRouter tarafından expose edilen context değerini dışarı taşır
  // (routerShim'in context'i private; dolaylı olarak NavLink/Routes davranışından test ederiz)
  return null;
};

// ─────────────────────────────────────────────────────────
// BrowserRouter
// ─────────────────────────────────────────────────────────

describe("BrowserRouter", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
  });

  it("renders its children", () => {
    render(
      <BrowserRouter>
        <span>içerik</span>
      </BrowserRouter>,
    );
    expect(screen.getByText("içerik")).toBeInTheDocument();
  });

  it("renders multiple children", () => {
    render(
      <BrowserRouter>
        <span>a</span>
        <span>b</span>
      </BrowserRouter>,
    );
    expect(screen.getByText("a")).toBeInTheDocument();
    expect(screen.getByText("b")).toBeInTheDocument();
  });

  it("initializes location from window.location.pathname", () => {
    window.history.replaceState({}, "", "/baslangic");
    // NavLink üzerinden dolaylı doğrulama — aktif link başlangıç path'ini yansıtmalı
    render(
      <BrowserRouter>
        <NavLink to="/baslangic" className={({ isActive }) => (isActive ? "aktif" : "")}>
          bağlantı
        </NavLink>
      </BrowserRouter>,
    );
    expect(screen.getByRole("link")).toHaveClass("aktif");
  });

  it("updates location on popstate event", () => {
    window.history.replaceState({}, "", "/ilk");
    render(
      <BrowserRouter>
        <NavLink to="/sonraki" className={({ isActive }) => (isActive ? "aktif" : "")}>
          link
        </NavLink>
      </BrowserRouter>,
    );
    expect(screen.getByRole("link")).not.toHaveClass("aktif");

    act(() => {
      window.history.pushState({}, "", "/sonraki");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });

    expect(screen.getByRole("link")).toHaveClass("aktif");
  });

  it("removes popstate listener on unmount", () => {
    window.history.replaceState({}, "", "/");
    const removeSpy = vi.spyOn(window, "removeEventListener");
    const { unmount } = render(
      <BrowserRouter>
        <span>test</span>
      </BrowserRouter>,
    );
    unmount();
    expect(removeSpy).toHaveBeenCalledWith("popstate", expect.any(Function));
    removeSpy.mockRestore();
  });
});

// ─────────────────────────────────────────────────────────
// Route
// ─────────────────────────────────────────────────────────

describe("Route", () => {
  it("renders the element prop", () => {
    render(<Route path="/test" element={<div>rota içeriği</div>} />);
    expect(screen.getByText("rota içeriği")).toBeInTheDocument();
  });

  it("returns null when element is undefined", () => {
    const { container } = render(<Route path="/test" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("returns null when element is null", () => {
    const { container } = render(<Route path="/test" element={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

// ─────────────────────────────────────────────────────────
// Routes
// ─────────────────────────────────────────────────────────

describe("Routes", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
  });

  it("renders the route matching the current location", () => {
    window.history.replaceState({}, "", "/profil");
    renderWithRouter(
      <Routes>
        <Route path="/profil" element={<div>Profil Sayfası</div>} />
        <Route path="/ayarlar" element={<div>Ayarlar Sayfası</div>} />
      </Routes>,
      "/profil",
    );
    expect(screen.getByText("Profil Sayfası")).toBeInTheDocument();
    expect(screen.queryByText("Ayarlar Sayfası")).not.toBeInTheDocument();
  });

  it("does not render non-matching routes", () => {
    renderWithRouter(
      <Routes>
        <Route path="/profil" element={<div>Profil</div>} />
        <Route path="/ayarlar" element={<div>Ayarlar</div>} />
      </Routes>,
      "/",
    );
    expect(screen.queryByText("Profil")).not.toBeInTheDocument();
    expect(screen.queryByText("Ayarlar")).not.toBeInTheDocument();
  });

  it("renders nothing when no path matches", () => {
    // normalizePath("*") → "/*" döner; "/*" === "*" karşılaştırması false olduğundan
    // path="*" sadece gerçek "/*" URL'ini yakalar, genel wildcard gibi çalışmaz.
    const { container } = renderWithRouter(
      <Routes>
        <Route path="/profil" element={<div>Profil</div>} />
        <Route path="*" element={<div>Bulunamadı</div>} />
      </Routes>,
      "/bilinmeyen-rota",
    );
    expect(screen.queryByText("Profil")).not.toBeInTheDocument();
    expect(screen.queryByText("Bulunamadı")).not.toBeInTheDocument();
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when no match and no fallback route", () => {
    const { container } = renderWithRouter(
      <Routes>
        <Route path="/profil" element={<div>Profil</div>} />
      </Routes>,
      "/baska",
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("matches root path exactly", () => {
    renderWithRouter(
      <Routes>
        <Route path="/" element={<div>Ana Sayfa</div>} />
        <Route path="/profil" element={<div>Profil</div>} />
      </Routes>,
      "/",
    );
    expect(screen.getByText("Ana Sayfa")).toBeInTheDocument();
    expect(screen.queryByText("Profil")).not.toBeInTheDocument();
  });

  it("renders first matching route when multiple paths match location", () => {
    // Routes.find() ilk eşleşeni döndürür; sıra önemlidir
    renderWithRouter(
      <Routes>
        <Route path="/chat" element={<div>İlk Chat</div>} />
        <Route path="/chat" element={<div>İkinci Chat</div>} />
      </Routes>,
      "/chat",
    );
    expect(screen.getByText("İlk Chat")).toBeInTheDocument();
    expect(screen.queryByText("İkinci Chat")).not.toBeInTheDocument();
  });

  it("path='*' matches the literal /*  URL", () => {
    // normalizePath("*") = "/*" — bu nedenle path="*" yalnızca "/*" URL'ini eşler
    renderWithRouter(
      <Routes>
        <Route path="*" element={<div>Yıldız Rota</div>} />
      </Routes>,
      "/*",
    );
    expect(screen.getByText("Yıldız Rota")).toBeInTheDocument();
  });

  it("handles routes without a path prop by defaulting to '*'", () => {
    renderWithRouter(
      <Routes>
        <Route element={<div>Path Olmayan Rota</div>} />
      </Routes>,
      "/*",
    );
    expect(screen.getByText("Path Olmayan Rota")).toBeInTheDocument();
  });

  it("updates rendered route after navigation", async () => {
    window.history.replaceState({}, "", "/chat");
    const user = userEvent.setup();

    render(
      <BrowserRouter>
        <NavLink to="/ayarlar">Ayarlar'a git</NavLink>
        <Routes>
          <Route path="/chat" element={<div>Chat Sayfası</div>} />
          <Route path="/ayarlar" element={<div>Ayarlar Sayfası</div>} />
        </Routes>
      </BrowserRouter>,
    );

    expect(screen.getByText("Chat Sayfası")).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "Ayarlar'a git" }));
    expect(screen.getByText("Ayarlar Sayfası")).toBeInTheDocument();
    expect(screen.queryByText("Chat Sayfası")).not.toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────
// RouterContext Varsayılan Değeri
// ─────────────────────────────────────────────────────────

describe("RouterContext Default Value", () => {
  it("provides a no-op navigate function to prevent crashes outside BrowserRouter", () => {
    expect(() => render(<Navigate to="/test" />)).not.toThrow();
  });
});

// ─────────────────────────────────────────────────────────
// Navigate
// ─────────────────────────────────────────────────────────

describe("Navigate", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/kaynak");
  });

  it("navigates to the target path on mount (pushState)", () => {
    renderWithRouter(
      <Routes>
        <Route path="/kaynak" element={<Navigate to="/hedef" />} />
        <Route path="/hedef" element={<div>Hedef Sayfa</div>} />
      </Routes>,
      "/kaynak",
    );
    expect(screen.getByText("Hedef Sayfa")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/hedef");
  });

  it("renders null — does not produce visible DOM output", () => {
    // Navigate'in kendi render çıktısı yok
    const { container } = renderWithRouter(<Navigate to="/baska" />, "/farkli");
    // Container sadece BrowserRouter wrapper'ı içerir, Navigate null döndürür
    expect(container.querySelector("a")).not.toBeInTheDocument();
  });

  it("uses replaceState when replace=true", () => {
    const replaceSpy = vi.spyOn(window.history, "replaceState");
    renderWithRouter(
      <Routes>
        <Route path="/kaynak" element={<Navigate to="/hedef" replace />} />
        <Route path="/hedef" element={<div>Hedef</div>} />
      </Routes>,
      "/kaynak",
    );
    expect(replaceSpy).toHaveBeenCalledWith({}, "", "/hedef");
    replaceSpy.mockRestore();
  });

  it("uses pushState when replace=false (default)", () => {
    const pushSpy = vi.spyOn(window.history, "pushState");
    renderWithRouter(
      <Routes>
        <Route path="/kaynak" element={<Navigate to="/hedef" />} />
        <Route path="/hedef" element={<div>Hedef</div>} />
      </Routes>,
      "/kaynak",
    );
    expect(pushSpy).toHaveBeenCalledWith({}, "", "/hedef");
    pushSpy.mockRestore();
  });

  it("does not navigate when already at target path", () => {
    window.history.replaceState({}, "", "/hedef");
    const pushSpy = vi.spyOn(window.history, "pushState");
    renderWithRouter(<Navigate to="/hedef" />, "/hedef");
    expect(pushSpy).not.toHaveBeenCalled();
    pushSpy.mockRestore();
  });
});

// ─────────────────────────────────────────────────────────
// NavLink
// ─────────────────────────────────────────────────────────

describe("NavLink", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
  });

  it("renders as an anchor element", () => {
    renderWithRouter(<NavLink to="/profil">Profil</NavLink>);
    expect(screen.getByRole("link")).toBeInTheDocument();
  });

  it("sets href to the normalized target path", () => {
    renderWithRouter(<NavLink to="/profil">Profil</NavLink>);
    expect(screen.getByRole("link")).toHaveAttribute("href", "/profil");
  });

  it("renders children text", () => {
    renderWithRouter(<NavLink to="/profil">Profilim</NavLink>);
    expect(screen.getByText("Profilim")).toBeInTheDocument();
  });

  it("applies string className regardless of active state", () => {
    renderWithRouter(
      <NavLink to="/baska" className="nav-item">
        Bağlantı
      </NavLink>,
    );
    expect(screen.getByRole("link")).toHaveClass("nav-item");
  });

  it("calls className function with isActive=true when location matches", () => {
    window.history.replaceState({}, "", "/profil");
    renderWithRouter(
      <NavLink to="/profil" className={({ isActive }) => (isActive ? "aktif" : "pasif")}>
        Profil
      </NavLink>,
      "/profil",
    );
    expect(screen.getByRole("link")).toHaveClass("aktif");
    expect(screen.getByRole("link")).not.toHaveClass("pasif");
  });

  it("calls className function with isActive=false when location does not match", () => {
    renderWithRouter(
      <NavLink to="/profil" className={({ isActive }) => (isActive ? "aktif" : "pasif")}>
        Profil
      </NavLink>,
      "/",
    );
    expect(screen.getByRole("link")).toHaveClass("pasif");
    expect(screen.getByRole("link")).not.toHaveClass("aktif");
  });

  it("calls children function with isActive=true when location matches", () => {
    window.history.replaceState({}, "", "/panel");
    renderWithRouter(
      <NavLink to="/panel">
        {({ isActive }) => <span>{isActive ? "seçili" : "normal"}</span>}
      </NavLink>,
      "/panel",
    );
    expect(screen.getByText("seçili")).toBeInTheDocument();
  });

  it("calls children function with isActive=false when location does not match", () => {
    renderWithRouter(
      <NavLink to="/panel">
        {({ isActive }) => <span>{isActive ? "seçili" : "normal"}</span>}
      </NavLink>,
      "/",
    );
    expect(screen.getByText("normal")).toBeInTheDocument();
  });

  it("navigates to target path on click", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/");
    renderWithRouter(
      <>
        <NavLink to="/profil">Profil</NavLink>
        <Routes>
          <Route path="/" element={<div>Ana Sayfa</div>} />
          <Route path="/profil" element={<div>Profil Sayfası</div>} />
        </Routes>
      </>,
      "/",
    );
    await user.click(screen.getByRole("link", { name: "Profil" }));
    expect(screen.getByText("Profil Sayfası")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/profil");
  });

  it("prevents default anchor navigation on click", async () => {
    const user = userEvent.setup();
    renderWithRouter(<NavLink to="/profil">Profil</NavLink>);
    // Gerçek sayfa yenilenmesi jsdom'da gerçekleşmez; pushState çağrısını doğrula
    const pushSpy = vi.spyOn(window.history, "pushState");
    await user.click(screen.getByRole("link"));
    expect(pushSpy).toHaveBeenCalled();
    pushSpy.mockRestore();
  });

  it("does not navigate when clicking an already-active link", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/profil");
    const pushSpy = vi.spyOn(window.history, "pushState");
    renderWithRouter(<NavLink to="/profil">Profil</NavLink>, "/profil");
    await user.click(screen.getByRole("link"));
    expect(pushSpy).not.toHaveBeenCalled();
    pushSpy.mockRestore();
  });

  it("passes extra props to the anchor element", () => {
    renderWithRouter(
      <NavLink to="/profil" data-testid="nav-profil" aria-label="Profil sayfası">
        Profil
      </NavLink>,
    );
    const link = screen.getByTestId("nav-profil");
    expect(link).toHaveAttribute("aria-label", "Profil sayfası");
  });

  it("updates active state after navigation", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/");
    renderWithRouter(
      <>
        <NavLink to="/panel" className={({ isActive }) => (isActive ? "aktif" : "")}>
          Panel
        </NavLink>
      </>,
      "/",
    );
    expect(screen.getByRole("link")).not.toHaveClass("aktif");
    await user.click(screen.getByRole("link"));
    expect(screen.getByRole("link")).toHaveClass("aktif");
  });
});

// ─────────────────────────────────────────────────────────
// MemoryRouter
// ─────────────────────────────────────────────────────────

describe("MemoryRouter", () => {
  it("falls back to root when initialEntries is empty", () => {
    render(
      <MemoryRouter initialEntries={[]}>
        <NavLink to="/" className={({ isActive }) => (isActive ? "aktif" : "")}>
          Ana Sayfa
        </NavLink>
      </MemoryRouter>,
    );

    expect(screen.getByRole("link", { name: "Ana Sayfa" })).toHaveClass("aktif");
  });

  it("initializes location from initialEntries[0]", () => {
    render(
      <MemoryRouter initialEntries={["/hafiza"]}>
        <NavLink to="/hafiza" className={({ isActive }) => (isActive ? "aktif" : "")}>
          Hafıza
        </NavLink>
      </MemoryRouter>,
    );

    expect(screen.getByRole("link", { name: "Hafıza" })).toHaveClass("aktif");
  });

  it("does not re-render route when navigating to the same path", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/profil"]}>
        <NavLink to="/profil">Profil</NavLink>
        <Routes>
          <Route path="/profil" element={<div>Profil Sayfası</div>} />
        </Routes>
      </MemoryRouter>,
    );

    const page = screen.getByText("Profil Sayfası");
    await user.click(screen.getByRole("link", { name: "Profil" }));
    expect(screen.getByText("Profil Sayfası")).toBe(page);
  });

  it("updates rendered route when navigating to a different path", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/ilk"]}>
        <NavLink to="/ikinci">İkinci</NavLink>
        <Routes>
          <Route path="/ilk" element={<div>İlk Sayfa</div>} />
          <Route path="/ikinci" element={<div>İkinci Sayfa</div>} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText("İlk Sayfa")).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "İkinci" }));
    expect(screen.getByText("İkinci Sayfa")).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────
// normalizePath — dolaylı davranış testleri
// ─────────────────────────────────────────────────────────

describe("normalizePath (dolaylı)", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
  });

  it("treats empty string as root path", () => {
    // Navigate to="" ile kök'e gitmeye çalışır — zaten kök'teyiz, hareket yok
    const pushSpy = vi.spyOn(window.history, "pushState");
    renderWithRouter(<Navigate to="" />, "/");
    expect(pushSpy).not.toHaveBeenCalled(); // "/" === "/" normalizasyon sayesinde
    pushSpy.mockRestore();
  });

  it("adds leading slash to paths without one", () => {
    renderWithRouter(<NavLink to="profil">Profil</NavLink>);
    expect(screen.getByRole("link")).toHaveAttribute("href", "/profil");
  });

  it("strips trailing slashes", () => {
    window.history.replaceState({}, "", "/profil");
    renderWithRouter(
      <NavLink to="/profil/" className={({ isActive }) => (isActive ? "aktif" : "")}>
        Profil
      </NavLink>,
      "/profil",
    );
    // "/profil/" normalleşince "/profil" olur → aktif olmalı
    expect(screen.getByRole("link")).toHaveClass("aktif");
  });

  it("normalizes multiple consecutive slashes in trailing position", () => {
    window.history.replaceState({}, "", "/");
    renderWithRouter(
      <NavLink to="///" className={({ isActive }) => (isActive ? "aktif" : "")}>
        Kök
      </NavLink>,
      "/",
    );
    // "///" → "/" normalize olur → aktif
    expect(screen.getByRole("link")).toHaveClass("aktif");
  });
});
