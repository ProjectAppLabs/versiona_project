import { act, render, screen } from '@testing-library/react';

import { PdfViewer } from '../PdfViewer';

jest.mock('react-pdf', () => {
  const React = jest.requireActual('react');
  return {
    pdfjs: { GlobalWorkerOptions: {} },
    Document: ({ children, onLoadSuccess }: { children: React.ReactNode; onLoadSuccess: (doc: { numPages: number }) => void }) => {
      const loaded = React.useRef(false);
      React.useEffect(() => {
        if (loaded.current) return;
        loaded.current = true;
        onLoadSuccess({ numPages: 1 });
      }, [onLoadSuccess]);
      return <div>{children}</div>;
    },
    Page: ({ width, onRenderSuccess }: { width: number; onRenderSuccess: (page: { getViewport: () => { width: number; height: number } }) => void }) => {
      const previousWidth = React.useRef(null);
      React.useEffect(() => {
        if (previousWidth.current === width) return;
        previousWidth.current = width;
        onRenderSuccess({ getViewport: () => ({ width: 600, height: 900 }) });
      }, [width, onRenderSuccess]);
      return <canvas data-testid="rendered-pdf" style={{ width, height: width * 1.5 }} />;
    },
  };
});

let observerCallback: ResizeObserverCallback;
const disconnect = jest.fn();

class TestResizeObserver {
  constructor(callback: ResizeObserverCallback) { observerCallback = callback; }
  observe() {}
  disconnect = disconnect;
}

function resizeContent(width: number) {
  act(() => {
    observerCallback([{ contentRect: { width } } as ResizeObserverEntry], {} as ResizeObserver);
  });
}

describe('PdfViewer available width', () => {
  beforeEach(() => {
    global.ResizeObserver = TestResizeObserver as unknown as typeof ResizeObserver;
    disconnect.mockClear();
  });

  it('waits for a positive available width before rendering a page', () => {
    render(<PdfViewer file="/contract.pdf" />);

    expect(screen.queryByTestId('rendered-pdf')).not.toBeInTheDocument();
  });

  it.each([
    { available: 364, maximum: 760, expected: 362 },
    { available: 787, maximum: 760, expected: 760 },
    { available: 320, maximum: 420, expected: 318 },
    { available: 1200, maximum: 420, expected: 420 },
  ])('renders $expected px in $available px with a $maximum px maximum', ({ available, maximum, expected }) => {
    render(<PdfViewer file="/contract.pdf" width={maximum} />);

    resizeContent(available);

    expect(screen.getByTestId('rendered-pdf')).toHaveStyle({ width: `${expected}px` });
  });

  it('keeps a highlight aligned when the available width shrinks', () => {
    render(<PdfViewer file="/contract.pdf" highlights={[{ page: 1, x0: 0.1, y0: 0.2, x1: 0.6, y1: 0.5 }]} />);
    resizeContent(762);

    resizeContent(402);

    expect(screen.getByTestId('diff-highlight')).toHaveStyle({ left: '40px', top: '120px', width: '200px', height: '180px' });
  });

  it('disconnects the width observer when the viewer unmounts', () => {
    const { unmount } = render(<PdfViewer file="/contract.pdf" />);

    unmount();

    expect(disconnect).toHaveBeenCalledTimes(1);
  });
});
