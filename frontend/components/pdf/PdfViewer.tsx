'use client';

/**
 * PDF viewer v1 (docs/plan/04 §3 — react-pdf, client-only). Renders from a
 * presigned URL or a local File (LocalPdfPreview). Page virtualization and
 * overlay layers (observations/diff) join in It2–It4.
 */

import { useEffect, useRef, useState } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';

import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';

import { Skeleton } from '@/components/ui/Skeleton';
import { bboxToCss, groupByPage, type NormalizedBBox } from '@/lib/pdf/coords';

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url
).toString();

interface PdfViewerProps {
  file: string | File;
  maxPages?: number;
  width?: number;
  onLoaded?: (pages: number) => void;
  /** Diff/observation overlays (normalized 0–1, top-left) — E1 highlights. */
  highlights?: NormalizedBBox[];
  highlightKind?: 'modified' | 'added' | 'removed';
  /** Page the viewer should scroll to (1-based) — section navigation. */
  scrollToPage?: number | null;
}

const HIGHLIGHT_CLASS: Record<string, string> = {
  modified: 'bg-amber-400/30 border border-amber-500/60',
  added: 'bg-emerald-400/25 border border-emerald-500/60',
  removed: 'bg-destructive/20 border border-destructive/60',
};

export function PdfViewer({
  file,
  maxPages,
  width = 760,
  onLoaded,
  highlights = [],
  highlightKind = 'modified',
  scrollToPage = null,
}: PdfViewerProps) {
  const [pageCount, setPageCount] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [pageSize, setPageSize] = useState<{ width: number; height: number } | null>(null);
  const [availableWidth, setAvailableWidth] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const pageRefs = useRef<Record<number, HTMLDivElement | null>>({});
  const byPage = groupByPage(highlights);
  // ResizeObserver measures the content box after the caller's paddings. Each
  // page has a one-pixel border on both sides; width remains a maximum.
  const renderedWidth = Math.max(0, Math.min(width, availableWidth - 2));

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const style = getComputedStyle(container);
    setAvailableWidth(container.clientWidth - parseFloat(style.paddingLeft || '0') - parseFloat(style.paddingRight || '0'));
    const observer = new ResizeObserver(([entry]) => {
      setAvailableWidth(entry.contentRect.width);
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!scrollToPage) return;
    const node = pageRefs.current[scrollToPage];
    node?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [scrollToPage, pageCount]);

  if (error) {
    return (
      <div
        data-testid="pdf-error"
        className="rounded-2xl border border-destructive/30 bg-destructive/5 p-6 text-sm text-destructive"
      >
        {error}
      </div>
    );
  }

  const pagesToRender = maxPages ? Math.min(pageCount, maxPages) : pageCount;

  return (
    <div ref={containerRef} data-testid="pdf-viewer" className="flex w-full min-w-0 flex-col items-center gap-4">
      {renderedWidth > 0 ? (
      <Document
        file={file}
        loading={<Skeleton className="h-[480px] w-full max-w-[760px]" />}
        onLoadSuccess={(doc) => {
          setPageCount(doc.numPages);
          onLoaded?.(doc.numPages);
        }}
        onLoadError={(err) => setError(err.message)}
        // Without this, pdf.js opens a native prompt() asking for the
        // password. Protected PDFs are rejected right here — before the
        // upload is even attempted (kit 1).
        onPassword={() =>
          setError(
            'El PDF está protegido con contraseña: quita la protección y vuelve a subirlo.'
          )
        }
      >
        {Array.from({ length: pagesToRender }, (_, index) => {
          const pageNumber = index + 1;
          const boxes = byPage.get(pageNumber) ?? [];
          return (
            <div
              key={index}
              ref={(node) => {
                pageRefs.current[pageNumber] = node;
              }}
              data-testid={`pdf-page-${pageNumber}`}
              className="relative mb-4 overflow-hidden rounded-xl border border-border shadow-sm"
            >
              <Page
                pageNumber={pageNumber}
                width={renderedWidth}
                renderAnnotationLayer={false}
                onRenderSuccess={(page) => {
                  const viewport = page.getViewport({ scale: 1 });
                  const scale = renderedWidth / viewport.width;
                  setPageSize({ width: renderedWidth, height: viewport.height * scale });
                }}
              />
              {pageSize && boxes.length > 0 ? (
                <div className="pointer-events-none absolute inset-0" data-testid="highlight-layer">
                  {boxes.map((bbox, boxIndex) => {
                    const css = bboxToCss(bbox, renderedWidth, pageSize.height * renderedWidth / pageSize.width);
                    return (
                      <div
                        key={boxIndex}
                        data-testid="diff-highlight"
                        className={`absolute rounded-sm ${HIGHLIGHT_CLASS[highlightKind]}`}
                        style={{
                          left: `${css.left}px`,
                          top: `${css.top}px`,
                          width: `${css.width}px`,
                          height: `${css.height}px`,
                        }}
                      />
                    );
                  })}
                </div>
              ) : null}
            </div>
          );
        })}
      </Document>
      ) : <Skeleton className="h-[480px] w-full max-w-[760px]" />}
      {maxPages && pageCount > maxPages ? (
        <p className="text-xs text-muted-foreground">
          +{pageCount - maxPages} páginas más en el documento completo
        </p>
      ) : null}
    </div>
  );
}
