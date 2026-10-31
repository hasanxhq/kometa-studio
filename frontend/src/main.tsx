import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "@fontsource-variable/space-grotesk";
import "./index.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";

import { App } from "./App";
import { urlBase } from "./base";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter basename={urlBase || undefined}>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
