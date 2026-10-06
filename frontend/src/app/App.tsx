import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router";

import { AuthGate } from "@/features/auth/AuthGate";
import { HomeScreen } from "@/features/home/HomeScreen";
import { AppShell, Placeholder } from "@/features/shell/AppShell";
import { ProjectLayout } from "@/features/shell/ProjectLayout";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 5_000, retry: 1, refetchOnWindowFocus: false } },
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthGate>
        <BrowserRouter>
          <Routes>
            <Route element={<AppShell />}>
              <Route index element={<HomeScreen />} />
              <Route path="exports" element={<Placeholder title="Exports" />} />
              <Route path="settings" element={<Placeholder title="Settings" />} />
              <Route path="p/:pid" element={<ProjectLayout />}>
                <Route index element={<Placeholder title="Here's what we found" />} />
                <Route path="*" element={<Placeholder title="Coming in this milestone" />} />
              </Route>
              <Route path="*" element={<Placeholder title="Not found" />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AuthGate>
    </QueryClientProvider>
  );
}
