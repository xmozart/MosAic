import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router";

import { AnalysisProgressScreen } from "@/features/analysis/AnalysisProgressScreen";
import { AnalysisSetupScreen } from "@/features/analysis/AnalysisSetupScreen";
import { DeepenRoute } from "@/features/analysis/DeepenRoute";
import { AuthGate } from "@/features/auth/AuthGate";
import { TripContextScreen } from "@/features/context/TripContextScreen";
import { EditsScreen } from "@/features/edits/EditsScreen";
import { ExportsIndex, ExportsScreen } from "@/features/exports/ExportsScreen";
import { WizardScreen } from "@/features/edits/WizardScreen";
import { HomeScreen } from "@/features/home/HomeScreen";
import { InventoryScreen } from "@/features/inventory/InventoryScreen";
import { ClipDetailScreen } from "@/features/library/ClipDetailScreen";
import { LibraryScreen } from "@/features/library/LibraryScreen";
import { PreviewScreen } from "@/features/preview/PreviewScreen";
import { SearchScreen } from "@/features/search/SearchScreen";
import { AppShell, Placeholder } from "@/features/shell/AppShell";
import { ProjectIndex } from "@/features/shell/ProjectIndex";
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
              <Route path="exports" element={<ExportsIndex />} />
              <Route path="settings" element={<Placeholder title="Settings" />} />
              <Route path="p/:pid" element={<ProjectLayout />}>
                <Route index element={<ProjectIndex />} />
                <Route path="inventory" element={<InventoryScreen />} />
                <Route path="context" element={<TripContextScreen />} />
                <Route path="analyze" element={<AnalysisSetupScreen />} />
                <Route path="analysis" element={<AnalysisProgressScreen />} />
                <Route path="deepen" element={<DeepenRoute />} />
                <Route path="library" element={<LibraryScreen />} />
                <Route path="clips/:aid" element={<ClipDetailScreen />} />
                <Route path="search" element={<SearchScreen />} />
                <Route path="edits" element={<EditsScreen />} />
                <Route path="edits/new" element={<WizardScreen />} />
                <Route path="edits/:eid" element={<PreviewScreen />} />
                <Route path="exports" element={<ExportsScreen />} />
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
