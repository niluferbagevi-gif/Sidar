import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "./lib/routerShim.js";
import App from "./App.js";
import "./index.css";

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Sidar frontend root elementi bulunamadı.");
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
