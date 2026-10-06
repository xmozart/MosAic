import "@testing-library/jest-dom/vitest";

// jsdom has no layout: a ResizeObserver that reports a fixed 1000 × 800 box, enough for
// virtualized grids to lay out columns in tests.
class FixedResizeObserver {
  constructor(private cb: ResizeObserverCallback) {}
  observe(target: Element) {
    const box = [{ inlineSize: 1000, blockSize: 800 }];
    this.cb(
      [{ target, contentRect: { width: 1000, height: 800 }, borderBoxSize: box, contentBoxSize: box } as unknown as ResizeObserverEntry],
      this as unknown as ResizeObserver,
    );
  }
  unobserve() {}
  disconnect() {}
}
if (typeof globalThis.ResizeObserver === "undefined") globalThis.ResizeObserver = FixedResizeObserver as unknown as typeof ResizeObserver;

// jsdom has no Element.scrollTo: set the position and fire "scroll", as a browser does,
// so virtualized lists mount the rows they scroll to.
if (typeof Element.prototype.scrollTo !== "function") {
  Element.prototype.scrollTo = function (this: Element, opts?: ScrollToOptions | number, y?: number) {
    const top = typeof opts === "number" ? (y ?? 0) : (opts?.top ?? this.scrollTop);
    this.scrollTop = top;
    this.dispatchEvent(new Event("scroll"));
  } as Element["scrollTo"];
}
