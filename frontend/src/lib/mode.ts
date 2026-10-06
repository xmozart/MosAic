import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";

/** Desktop or server: what the folder flows look like (S4). */
export function useMode(): "desktop" | "server" | undefined {
  const q = useQuery({
    queryKey: ["auth", "status"],
    queryFn: async () => (await api.GET("/api/auth/status")).data as { mode: string } | undefined,
  });
  const m = q.data?.mode;
  return m === "server" ? "server" : m === "desktop" ? "desktop" : undefined;
}
