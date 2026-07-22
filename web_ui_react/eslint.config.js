import js from "@eslint/js";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import jsxA11y from "eslint-plugin-jsx-a11y";

const browserGlobals = {
  window: "readonly",
  document: "readonly",
  localStorage: "readonly",
  location: "readonly",
  fetch: "readonly",
  FormData: "readonly",
  WebSocket: "readonly",
  crypto: "readonly",
  console: "readonly",
  URL: "readonly",
  URLSearchParams: "readonly",
  btoa: "readonly",
  atob: "readonly",
  Blob: "readonly",
  File: "readonly",
  Audio: "readonly",
  AudioContext: "readonly",
  MediaRecorder: "readonly",
  navigator: "readonly",
  Event: "readonly",
  StorageEvent: "readonly",
  PopStateEvent: "readonly",
  Storage: "readonly",
  setTimeout: "readonly",
  clearTimeout: "readonly",
  AbortController: "readonly",
  AbortSignal: "readonly",
};

const vitestGlobals = {
  describe: "readonly",
  it: "readonly",
  test: "readonly",
  expect: "readonly",
  vi: "readonly",
  beforeEach: "readonly",
  afterEach: "readonly",
  beforeAll: "readonly",
  afterAll: "readonly",
  global: "readonly",
};

export default [
  {
    files: ["src/**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      parserOptions: {
        ecmaFeatures: {
          jsx: true,
        },
      },
      globals: browserGlobals,
    },
    plugins: {
      react,
      "react-hooks": reactHooks,
      "jsx-a11y": jsxA11y,
    },
    settings: {
      react: {
        version: "detect",
      },
    },
    rules: {
      ...js.configs.recommended.rules,
      ...react.configs.recommended.rules,
      // Bu proje daha önce hiç a11y lint kapısına sahip değildi (%100 unit
      // coverage bunu yakalamaz). jsx-a11y'nin recommended seti eklendi;
      // repo genelinde tarandığında yalnızca 5 küçük bulgu çıktı, hepsi bu
      // PR'da düzeltildi/gerekçelendirildi (bkz. GraphView.jsx'teki
      // eslint-disable yorumu).
      ...jsxA11y.configs.recommended.rules,
      // Automatic JSX runtime (Vite's @vitejs/plugin-react default): React
      // does not need to be in scope for JSX to compile, so these two
      // classic-runtime rules would fight the no-unused-vars cleanup below.
      "react/react-in-jsx-scope": "off",
      "react/jsx-uses-react": "off",
      // This codebase has no prop-types dependency and types components via
      // the in-progress TypeScript migration instead (see tsconfig.json);
      // enforcing this now would demand a parallel, unrelated PropTypes
      // rollout. Revisit once more of the tree is converted to .tsx.
      "react/prop-types": "off",
      // Kademeli sıkılaştırma: react-hooks v7'nin tam "recommended"/"recommended-latest"
      // seti (React Compiler'a yönelik immutability/purity/set-state-in-render gibi
      // ek kurallar) burada bilinçli olarak etkinleştirilmedi — reviewer talebi
      // özellikle hook bağımlılık dizisi hataları (exhaustive-deps) ve hook
      // çağrı kuralları (rules-of-hooks) içindi; daha geniş kural seti ayrı bir
      // değerlendirme/temizlik turu gerektirir.
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
      // Standard convention for intentionally-discarded bindings (e.g.
      // destructuring a prop out solely to exclude it from a `...rest` spread).
      "no-unused-vars": ["error", { args: "after-used", argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
    },
  },
  {
    files: ["src/**/*.{test,spec}.{js,jsx}"],
    languageOptions: {
      globals: vitestGlobals,
    },
  },
  {
    files: ["src/test/launcher_script.test.js"],
    languageOptions: {
      // launcher_gui/script.js is a classic (non-module) script, side-effect
      // imported here; it attaches these via `window.foo = foo`, which this
      // jsdom test environment resolves as real globals at runtime, but
      // eslint can't see that dynamic assignment statically.
      globals: {
        launchSidar: "readonly",
        animateStepTransition: "readonly",
      },
    },
  },
];
