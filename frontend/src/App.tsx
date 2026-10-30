import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Suspense, lazy, type ComponentType } from "react";
import { Navigate, Route, Routes } from "react-router";

import { AdvancedProvider } from "./advanced";
import { AuthGate } from "./components/AuthGate";
import { Layout } from "./components/Layout";
import { pages } from "./nav";
import { ActivityHistory } from "./pages/ActivityHistory";
import { ActivityQueue } from "./pages/ActivityQueue";
import { FileEditor } from "./pages/FileEditor";

// The form editor brings Kometa's schema checking; load it when it's opened.
const ItemEditor = lazy(() => import("./pages/ItemEditor"));
import { Libraries } from "./pages/Libraries";
import { LibraryDetail } from "./pages/LibraryDetail";
import { Placeholder } from "./pages/Placeholder";
import { RunDetail } from "./pages/RunDetail";
import { SettingsGeneral } from "./pages/SettingsGeneral";
import { SettingsPlex } from "./pages/SettingsPlex";
import { SystemBackup } from "./pages/SystemBackup";
import { SystemStatus } from "./pages/SystemStatus";
import { SystemTasks } from "./pages/SystemTasks";
import { SystemUpdates } from "./pages/SystemUpdates";

// Pages that exist so far; every other nav entry shows a placeholder.
const built: Record<string, ComponentType> = {
  "/libraries": Libraries,
  "/activity/queue": ActivityQueue,
  "/activity/history": ActivityHistory,
  "/system/status": SystemStatus,
  "/system/tasks": SystemTasks,
  "/system/backup": SystemBackup,
  "/system/updates": SystemUpdates,
  "/settings/general": SettingsGeneral,
  "/settings/plex": SettingsPlex,
};

export function App({ queryClient = new QueryClient() }: { queryClient?: QueryClient }) {
  return (
    <QueryClientProvider client={queryClient}>
      <AdvancedProvider>
        <AuthGate>
          <Routes>
            <Route element={<Layout />}>
              <Route index element={<Navigate to="/libraries" replace />} />
              {pages.map((page) => {
                const Built = built[page.path];
                return <Route key={page.path} path={page.path} element={Built ? <Built /> : <Placeholder page={page} />} />;
              })}
              <Route path="/activity/queue/:id" element={<RunDetail />} />
              <Route path="/libraries/:name" element={<LibraryDetail />} />
              <Route path="/files" element={<FileEditor />} />
              <Route
                path="/items"
                element={
                  <Suspense fallback={<p className="text-muted">Loading…</p>}>
                    <ItemEditor />
                  </Suspense>
                }
              />
              <Route path="*" element={<p className="text-muted">Page not found.</p>} />
            </Route>
          </Routes>
        </AuthGate>
      </AdvancedProvider>
    </QueryClientProvider>
  );
}
