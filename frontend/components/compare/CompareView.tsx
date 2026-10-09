'use client';

/**
 * THE STAR SCREEN (flow E1 — docs/plan/04 §2): three views over one
 * comparison, synchronized BY SECTION (never by pixel).
 */

import dynamic from 'next/dynamic';
import { useEffect, useState } from 'react';

import { SectionChangeList } from '@/components/compare/SectionChangeList';
import { AsyncBoundary } from '@/components/ui/AsyncBoundary';
import { EmptyState } from '@/components/ui/EmptyState';
import { Skeleton } from '@/components/ui/Skeleton';
import { Tabs } from '@/components/ui/Tabs';
import { countsByType, nextChanged, sectionTarget } from '@/lib/compare/sync';
import { useDict } from '@/lib/i18n/dictionaries';
import { useCompareStore } from '@/lib/stores/compareStore';
import { useVersionStore } from '@/lib/stores/versionStore';
import { api } from '@/lib/services/http';
import { useToast } from '@/components/ui/toast';

const PdfViewer = dynamic(
  () => import('@/components/pdf/PdfViewer').then((m) => m.PdfViewer),
  { ssr: false, loading: () => <Skeleton className="h-[420px] w-full" /> }
);

export type CompareViewMode = 'side' | 'sections' | 'summary';

interface CompareViewProps {
  documentId: string;
  fromVersionId: string;
  toVersionId: string;
  view: CompareViewMode;
  onViewChange: (view: CompareViewMode) => void;
}

export function CompareView({
  documentId,
  fromVersionId,
  toVersionId,
  view,
  onViewChange,
}: CompareViewProps) {
  const t = useDict('compare');
  const saved = useDict('savedComparisons');
  const common = useDict('common');
  const { toast } = useToast();
  const comparison = useCompareStore((s) => s.comparison);
  const isLoading = useCompareStore((s) => s.isLoading);
  const error = useCompareStore((s) => s.error);
  const activeSection = useCompareStore((s) => s.activeSection);
  const compare = useCompareStore((s) => s.compare);
  const fetchSectionDiff = useCompareStore((s) => s.fetchSectionDiff);
  const setActiveSection = useCompareStore((s) => s.setActiveSection);
  const diffs = useCompareStore((s) => s.diffs);
  const fetchFileUrl = useVersionStore((s) => s.fetchFileUrl);

  const [fromUrl, setFromUrl] = useState<string | null>(null);
  const [toUrl, setToUrl] = useState<string | null>(null);
  const [hideUnchanged, setHideUnchanged] = useState(true);

  useEffect(() => {
    void compare(documentId, fromVersionId, toVersionId);
  }, [compare, documentId, fromVersionId, toVersionId]);

  useEffect(() => {
    void fetchFileUrl(fromVersionId).then(setFromUrl);
    void fetchFileUrl(toVersionId).then(setToUrl);
  }, [fetchFileUrl, fromVersionId, toVersionId]);

  // Deep link (#sec-<key>) selects the section on arrival.
  useEffect(() => {
    if (!comparison) return;
    const hash = typeof window !== 'undefined' ? window.location.hash : '';
    const key = hash.startsWith('#sec-') ? hash.slice(5) : null;
    if (key && comparison.section_changes.some((c) => c.stable_key === key)) {
      setActiveSection(key);
      void fetchSectionDiff(key);
    }
  }, [comparison, setActiveSection, fetchSectionDiff]);

  const selectSection = async (key: string) => {
    setActiveSection(key);
    await fetchSectionDiff(key);
    if (typeof window !== 'undefined') {
      window.history.replaceState(null, '', `#sec-${key}`);
    }
  };

  const activeDiff = activeSection ? diffs[activeSection] : undefined;
  const target = activeDiff
    ? sectionTarget(activeDiff.bboxes_from, activeDiff.bboxes_to)
    : { fromPage: null, toPage: null };
  const counts = comparison ? countsByType(comparison.section_changes) : null;

  return (
    <div data-testid="compare-view">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">{t.title}</h1>
          {comparison ? (
            <p className="text-sm text-muted-foreground">
              v{comparison.from_number} → v{comparison.to_number} · {comparison.summary.text}
            </p>
          ) : null}
        </div>
        {/* Wraps below the title on narrow screens: at 412 px the three
            controls plus the tabs need ~442 px and used to push the page
            sideways (LAY-1). */}
        <div className="flex flex-wrap items-center gap-2">
          {comparison ? (
            <button
              data-testid="save-comparison"
              className="min-h-11 rounded-full border border-border px-3 py-1.5 text-sm hover:bg-accent"
              onClick={() => {
                const name = window.prompt(saved.name);
                if (!name?.trim()) return;
                void api
                  .post(`comparisons/${comparison.public_id}/save/`, { name: name.trim() })
                  .then(() => toast(saved.saved, 'success'))
                  .catch((err) =>
                    toast(err.response?.data?.error ?? common.error, 'error')
                  );
              }}
              type="button"
            >
              {saved.save}
            </button>
          ) : null}
          {comparison?.has_changes ? (
            <button
              data-testid="next-change"
              className="min-h-11 rounded-full border border-border px-3 py-1.5 text-sm hover:bg-accent"
              onClick={() => {
                const next = nextChanged(comparison.section_changes, activeSection);
                if (next) void selectSection(next.stable_key);
              }}
              type="button"
            >
              {t.nextChange}
            </button>
          ) : null}
          <Tabs
            items={[
              { id: 'side', label: t.views.side },
              { id: 'sections', label: t.views.sections },
              { id: 'summary', label: t.views.summary },
            ]}
            active={view}
            onChange={(id) => onViewChange(id as CompareViewMode)}
          />
        </div>
      </div>

      <AsyncBoundary
        isLoading={isLoading}
        error={error}
        onRetry={() => void compare(documentId, fromVersionId, toVersionId)}
        retryLabel={common.retry}
        skeleton={<Skeleton className="h-[420px] w-full" />}
      >
        {comparison && !comparison.has_changes ? (
          <div data-testid="no-changes">
            <EmptyState title={t.noChanges} description={t.noChangesBody} />
          </div>
        ) : comparison ? (
          <>
            {view === 'summary' ? (
              <dl data-testid="change-summary" className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {(['modified', 'added', 'removed', 'unchanged'] as const).map((key) => (
                  <div key={key} className="rounded-2xl border border-border bg-card p-4">
                    <dt className="text-xs text-muted-foreground">{t.change[key]}</dt>
                    <dd data-testid={`count-${key}`} className="mt-1 text-2xl font-semibold">
                      {counts?.[key] ?? 0}
                    </dd>
                  </div>
                ))}
              </dl>
            ) : null}

            {view === 'sections' ? (
              <SectionChangeList
                changes={comparison.section_changes}
                activeKey={activeSection}
                hideUnchanged={hideUnchanged}
                onToggleHideUnchanged={() => setHideUnchanged((v) => !v)}
                onSelect={(key) => void selectSection(key)}
              />
            ) : null}

            {view === 'side' ? (
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-[260px_1fr_1fr]">
                <aside className="lg:max-h-[70vh] lg:overflow-y-auto">
                  <SectionChangeList
                    changes={comparison.section_changes}
                    activeKey={activeSection}
                    hideUnchanged={hideUnchanged}
                    onToggleHideUnchanged={() => setHideUnchanged((v) => !v)}
                    onSelect={(key) => void selectSection(key)}
                  />
                </aside>
                <section data-testid="side-before" className="min-w-0">
                  <h2 className="mb-2 text-sm font-medium text-muted-foreground">
                    {t.before} · v{comparison.from_number}
                  </h2>
                  {fromUrl ? (
                    <PdfViewer
                      file={fromUrl}
                      width={420}
                      highlights={activeDiff?.bboxes_from ?? []}
                      highlightKind={
                        activeDiff?.change_type === 'removed' ? 'removed' : 'modified'
                      }
                      scrollToPage={target.fromPage}
                    />
                  ) : (
                    <Skeleton className="h-[420px] w-full" />
                  )}
                </section>
                <section data-testid="side-after" className="min-w-0">
                  <h2 className="mb-2 text-sm font-medium text-muted-foreground">
                    {t.after} · v{comparison.to_number}
                  </h2>
                  {toUrl ? (
                    <PdfViewer
                      file={toUrl}
                      width={420}
                      highlights={activeDiff?.bboxes_to ?? []}
                      highlightKind={activeDiff?.change_type === 'added' ? 'added' : 'modified'}
                      scrollToPage={target.toPage}
                    />
                  ) : (
                    <Skeleton className="h-[420px] w-full" />
                  )}
                </section>
              </div>
            ) : null}
          </>
        ) : null}
      </AsyncBoundary>
    </div>
  );
}
