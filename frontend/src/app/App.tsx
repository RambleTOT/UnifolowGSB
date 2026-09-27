import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import type { ReactNode } from "react";

import { AppShell } from "../components/layout/AppShell";
import { ToastProvider } from "../components/common/Toasts";
import { CheckpointsPage } from "../pages/CheckpointsPage";
import { EventDetailPage } from "../pages/EventDetailPage";
import { EventsPage } from "../pages/EventsPage";
import { HomePage } from "../pages/HomePage";
import { QueuesPage } from "../pages/QueuesPage";
import { ReportsPage } from "../pages/ReportsPage";
import { SettingsPage } from "../pages/SettingsPage";
import { LoginPage } from "../pages/LoginPage";
import { MarkupPage } from "../pages/MarkupPage";
import { MonitorPage } from "../pages/MonitorPage";
import { NotFoundPage } from "../pages/NotFoundPage";
import { SourceFormPage } from "../pages/SourceFormPage";
import { SourcesPage } from "../pages/SourcesPage";
import { SessionProvider, useSession } from "../state/session";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 5_000 },
  },
});

function RequireSession({ children }: { children: ReactNode }) {
  const { user, loading } = useSession();
  const location = useLocation();

  if (loading) {
    return (
      <div className="boot" role="status">
        Загружаем UniFlow…
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }

  return <>{children}</>;
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <SessionProvider>
          <ToastProvider>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route
                element={
                  <RequireSession>
                    <AppShell />
                  </RequireSession>
                }
              >
                <Route path="/" element={<HomePage />} />
                <Route path="/monitor" element={<MonitorPage />} />
                <Route path="/sources" element={<SourcesPage />} />
                <Route path="/sources/new" element={<SourceFormPage />} />
                <Route path="/sources/:id/edit" element={<SourceFormPage />} />
                <Route path="/sources/:id/markup" element={<MarkupPage />} />
                <Route path="/queues" element={<QueuesPage />} />
                <Route path="/checkpoints" element={<CheckpointsPage />} />
                <Route path="/events" element={<EventsPage />} />
                <Route path="/events/:id" element={<EventDetailPage />} />
                <Route path="/reports" element={<ReportsPage />} />
                <Route path="/settings" element={<SettingsPage />} />
                <Route path="*" element={<NotFoundPage />} />
              </Route>
            </Routes>
          </ToastProvider>
        </SessionProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
