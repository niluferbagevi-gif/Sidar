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
      globals: {
        window: "readonly",
        document: "readonly",
        localStorage: "readonly",
        location: "readonly",
        fetch: "readonly",
        FormData: "readonly",
        WebSocket: "readonly",
        crypto: "readonly",
        console: "readonly",
      },
    },
    rules: {},
  },
];