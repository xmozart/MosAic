import { useQuery } from "@tanstack/react-query";
import { Navigate, useParams } from "react-router";

import { api } from "@/api/client";

/** `/p/:pid`: an analysed trip opens in its library, a new one at its inventory (S5). */
export function ProjectIndex() {
  const { pid } = useParams();
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: async () => (await api.GET("/api/projects")).data as { items: { id: string; card: { analyzed?: boolean } | null }[] } | undefined,
  });
  if (projects.isLoading) return null;
  if (!projects.data) return <Navigate replace to="inventory" />;
  const row = projects.data.items.find((p) => p.id === pid);
  return <Navigate replace to={row?.card?.analyzed ? "library" : "inventory"} />;
}
