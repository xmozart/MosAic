import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router";

import { AuthGate } from "@/features/auth/AuthGate";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 5_000, retry: 1, refetchOnWindowFocus: false } },
});

function Placeholder() {
  return (
    <main className="flex h-full items-center justify-center bg-bg">
      <p className="text-subhead text-text-muted">Your trip, told well.</p>
    </main>
  );
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthGate>
        <BrowserRouter>
          <Routes>
            <Route path="*" element={<Placeholder />} />
          </Routes>
        </BrowserRouter>
      </AuthGate>
    </QueryClientProvider>
  );
}
