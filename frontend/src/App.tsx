import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ComponentType } from "react";
import { Navigate, Route, Routes } from "react-router";

import { AdvancedProvider } from "./advanced";
import { Layout } from "./components/Layout";
import { pages } from "./nav";
import { ActivityQueue } from "./pages/ActivityQueue";
import { Placeholder } from "./pages/Placeholder";
import { RunDetail } from "./pages/RunDetail";
import { SettingsPlex } from "./pages/SettingsPlex";
import { SystemStatus } from "./pages/SystemStatus";
import { SystemTasks } from "./pages/SystemTasks";

// Pages that exist so far; every other nav entry shows a placeholder.
const built: Record<string, ComponentType> = {
  "/activity/queue": ActivityQueue,
  "/system/status": SystemStatus,
  "/system/tasks": SystemTasks,
  "/settings/plex": SettingsPlex,
};

export function App({ queryClient = new QueryClient() }: { queryClient?: QueryClient }) {
  return (
    <QueryClientProvider client={queryClient}>
      <AdvancedProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Navigate to="/libraries" replace />} />
            {pages.map((page) => {
              const Built = built[page.path];
              return <Route key={page.path} path={page.path} element={Built ? <Built /> : <Placeholder page={page} />} />;
            })}
            <Route path="/activity/queue/:id" element={<RunDetail />} />
            <Route path="*" element={<p className="text-muted">Page not found.</p>} />
          </Route>
        </Routes>
      </AdvancedProvider>
    </QueryClientProvider>
  );
}
