import type { Meta, StoryObj } from "@storybook/react-vite";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import type { Density } from "@/lib/domain";
import { frame } from "@/stories/frames";

import { ClipInspector } from "./ClipInspector";
import { DETAIL, GROUPS, item } from "./fixtures";
import { BulkBar, DayScrubber, KeyHints } from "./LibraryChrome";
import { LibraryGrid } from "./LibraryGrid";
import { LibraryToolbar } from "./LibraryToolbar";
import type { LibraryItem } from "./model";

const meta: Meta = { title: "Screens/S10 Library" };
export default meta;
type Story = StoryObj;

const noop = () => {};
const qc = new QueryClient({ defaultOptions: { queries: { retry: false, enabled: false } } });

function Screen(p: { items?: LibraryItem[]; density?: Density; selection?: number[]; banner?: ReactNode; inspector?: boolean; empty?: boolean; rejectedButton?: string }) {
  const items = p.items ?? Array.from({ length: 12 }, (_, i) => item(i));
  return (
    <QueryClientProvider client={qc}>
      <div className="relative flex h-[900px] w-[1368px] overflow-hidden rounded-lg border border-border bg-bg">
        <div className="flex min-w-0 flex-1 flex-col">
          <LibraryToolbar
            filters={{}}
            statusView="default"
            onStatusView={noop}
            onFilters={noop}
            days={[]}
            cameras={[]}
            group="day"
            onGroup={noop}
            density={p.density ?? "comfortable"}
            onDensity={noop}
            onSearch={noop}
            onDeepen={noop}
            onCreateEdit={noop}
          />
          {p.banner && <div className="px-6 pt-3">{p.banner}</div>}
          {p.rejectedButton && (
            <div className="px-6 pt-3">
              <Button size="sm" variant="ghost">
                {p.rejectedButton}
              </Button>
            </div>
          )}
          {p.empty ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-3">
              <p className="text-body text-text-muted">No clips match.</p>
              <Button>Clear filters</Button>
            </div>
          ) : (
            <StoryGrid items={items} density={p.density ?? "comfortable"} selection={p.selection ?? [1]} />
          )}
          <KeyHints />
        </div>
        <DayScrubber days={GROUPS.map((g) => ({ key: g.key, n: g.day! }))} current={GROUPS[0]!.key} onJump={noop} />
        {p.inspector !== false && <ClipInspector clip={DETAIL} proxyUrl={undefined} frameUrl={(i) => frame(i)} onDecide={noop} onOpenFull={noop} onClose={noop} onShowClip={noop} />}
        {(p.selection?.length ?? 0) >= 2 && <BulkBar count={p.selection!.length} onDecide={noop} onClear={noop} />}
      </div>
    </QueryClientProvider>
  );
}

function StoryGrid({ items, density, selection }: { items: LibraryItem[]; density: Density; selection: number[] }) {
  return (
    <LibraryGrid
      pid="story"
      groups={GROUPS}
      items={items}
      frameUrl={(i) => frame(i)}
      density={density}
      collapsed={new Set()}
      selection={new Set(selection)}
      focus={selection[0] ?? null}
      hasMore={false}
      loadingMore={false}
      onEnd={noop}
      onToggleGroup={noop}
      onSelect={noop}
      onOpen={noop}
      onFocus={noop}
    />
  );
}

export const Default: Story = { render: () => <Screen /> };
export const Compact: Story = { render: () => <Screen density="compact" inspector={false} /> };
export const BulkSelection: Story = { render: () => <Screen selection={[1, 2, 3, 4]} inspector={false} /> };
export const Preliminary: Story = {
  render: () => (
    <Screen
      items={Array.from({ length: 12 }, (_, i) => item(i, i > 5 ? { status_shown: null, decided_by: null, caption: null } : {}))}
      banner={<Banner kind="info">Analysis is still running. Clips without a decision yet show no chip, and early edits are marked preliminary.</Banner>}
    />
  ),
};
export const RejectedShown: Story = {
  render: () => (
    <Screen
      rejectedButton="Hide rejected"
      items={Array.from({ length: 12 }, (_, i) => item(i, i % 4 === 1 ? { status_shown: "REJECT", decided_by: i % 8 === 1 ? "user" : "ai" } : {}))}
    />
  ),
};
export const UserDecisions: Story = {
  render: () => (
    <Screen
      items={Array.from({ length: 12 }, (_, i) =>
        item(i, i < 4 ? { decided_by: "user", status_shown: "USE", decision: { ...item(i).decision, disposition: "USE", stars: 4 - (i % 3) } } : {}),
      )}
    />
  ),
};
export const EmptyFilter: Story = { render: () => <Screen empty inspector={false} rejectedButton="Show rejected (14)" /> };
export const OfflineSource: Story = { render: () => <Screen items={Array.from({ length: 6 }, (_, i) => item(i, { offline: i === 1 }))} /> };
export const Light: Story = { globals: { theme: "light" }, render: () => <Screen /> };
