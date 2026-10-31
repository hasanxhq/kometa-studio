import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "@fontsource-variable/space-grotesk";
import "./index.css";

import { QueryClient } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider, createBrowserRouter } from "react-router";

import { App } from "./App";
import { urlBase } from "./base";

const queryClient = new QueryClient();

// The routes are in App. A router made this way, rather than BrowserRouter, is what lets a page ask before it's left.
const router = createBrowserRouter([{ path: "*", element: <App queryClient={queryClient} /> }], { basename: urlBase || undefined });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
