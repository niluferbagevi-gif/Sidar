import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "./lib/routerShim.tsx";
import App from "./App.tsx";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);