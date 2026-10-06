import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";

import { RESULTS, SUGGESTIONS } from "./fixtures";
import { SearchScreen } from "./SearchScreen";
import { SearchView, type SearchViewProps } from "./SearchView";

const noop = () => {};
const base: SearchViewProps = {
  query: "people laughing",
  mode: "all",
  items: RESULTS,
  visual: "ok",
  suggestions: SUGGESTIONS,
  frameUrl: (i) => `/f/${i}`,
  onSearch: noop,
  onMode: noop,
  onOpen: noop,
};

describe("SearchView", () => {
  it("results say what matched, and the owner's decisions show as theirs", () => {
    render(<SearchView {...base} />);
    expect(screen.getByText("12 results for “people laughing”")).toBeInTheDocument();
    const first = screen.getAllByRole("listitem")[0]!;
    expect(within(first).getByText(/said: “it's right there!” · looks like: laughing/)).toBeInTheDocument();
    expect(within(first).getByLabelText("USE, set by you")).toBeInTheDocument();
    expect(within(screen.getAllByRole("listitem")[1]!).getByLabelText("MAYBE, suggested by AI")).toBeInTheDocument();
  });

  it("no results offers this trip's suggestions; Enter and a suggestion search", () => {
    const search = vi.fn();
    render(<SearchView {...base} query="penguins" items={[]} onSearch={search} />);
    expect(screen.getByText("No clips match “penguins”")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "toucan" })).toHaveLength(1); // offered once
    fireEvent.click(screen.getByRole("button", { name: "toucan" }));
    expect(search).toHaveBeenLastCalledWith("toucan");
    const box = screen.getByLabelText("Search footage");
    fireEvent.change(box, { target: { value: "dolphins" } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(search).toHaveBeenLastCalledWith("dolphins");
    fireEvent.keyDown(box, { key: "Escape" });
    expect(box).toHaveValue("");
  });

  it("analysis incomplete and searching states", () => {
    const { rerender } = render(<SearchView {...base} visual="unavailable" />);
    expect(screen.getByText(/results may improve once it finishes/)).toBeInTheDocument();
    rerender(<SearchView {...base} items={undefined} />);
    expect(screen.getByText("Searching")).toBeInTheDocument();
    const retry = vi.fn();
    rerender(<SearchView {...base} items={undefined} error onRetry={retry} />);
    expect(screen.queryByText("Searching")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalled();
    rerender(<SearchView {...base} query="" items={undefined} />);
    expect(screen.getByText("Search this trip")).toBeInTheDocument();
    expect(screen.queryByText("Searching")).toBeNull();
  });
});

const calls: { path: string; query?: Record<string, unknown> }[] = [];
let fail = false;
vi.mock("@/api/client", () => ({
  api: {
    GET: (path: string, o?: { params?: { query?: Record<string, unknown> } }) => {
      calls.push({ path, query: o?.params?.query });
      if (path.endsWith("/suggestions")) return Promise.resolve({ data: { suggestions: SUGGESTIONS } });
      if (fail) return Promise.resolve({ error: { detail: "down" } });
      return Promise.resolve({ data: { items: RESULTS.slice(0, 3), visual: "ok" } });
    },
  },
}));

function mount(url: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route path="/p/:pid/search" element={<SearchScreen />} />
          <Route path="/p/:pid/clips/:aid" element={<p>clip page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("SearchScreen keeps the query in the URL, switches mode and opens a result", async () => {
  fail = false;
  mount("/p/P1/search?q=toucan");
  expect(await screen.findByText("3 results for “toucan”")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("radio", { name: "Speech" }));
  await waitFor(() => expect(calls.some((c) => c.query?.mode === "speech" && c.query.q === "toucan")).toBe(true));
  fireEvent.keyDown(document.body, { key: "/" });
  expect(document.activeElement).toBe(screen.getByLabelText("Search footage"));
  fireEvent.click(await screen.findByRole("button", { name: RESULTS[0]!.name! }));
  expect(await screen.findByText("clip page")).toBeInTheDocument();
});


it("no query is idle, a bad mode means All, and a failure offers a retry", async () => {
  fail = false;
  mount("/p/P1/search");
  expect(await screen.findByText("Search this trip")).toBeInTheDocument();
  expect(screen.queryByText("Searching")).toBeNull();
  mount("/p/P1/search?q=bird&mode=foo");
  await waitFor(() => expect(calls.some((c) => c.query?.q === "bird" && c.query.mode === "all")).toBe(true));
  fail = true;
  mount("/p/P1/search?q=fish");
  expect(await screen.findByText("Couldn't search right now.")).toBeInTheDocument();
});
