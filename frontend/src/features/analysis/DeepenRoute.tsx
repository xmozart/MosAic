import { useLocation, useNavigate, useParams } from "react-router";

import { Placeholder } from "@/features/shell/AppShell";

import { DeepenDialog } from "./DeepenDialog";

/** `/p/:pid/deepen` (⌘K "Deepen analysis…"): S25 over the library. The Library passes its
 * selected segment ids in the navigation state. */
export function DeepenRoute() {
  const { pid = "" } = useParams();
  const navigate = useNavigate();
  const selection = (useLocation().state as { segmentIds?: number[] } | null)?.segmentIds ?? [];
  return (
    <>
      <Placeholder title="Library" />
      <DeepenDialog pid={pid} open selection={selection} onClose={() => navigate(`/p/${pid}/library`, { replace: true })} />
    </>
  );
}
