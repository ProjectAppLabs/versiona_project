'use client';

/** D3: anchored observation threads for a version — status filter, replies,
 * the I14 transitions and the anchor health per version. */

import { useSearchParams } from 'next/navigation';
import { useEffect, useState } from 'react';

import { EmptyState } from '@/components/ui/EmptyState';
import { Modal } from '@/components/ui/Modal';
import { useToast } from '@/components/ui/toast';
import { useDict } from '@/lib/i18n/dictionaries';
import type { NormalizedBBox } from '@/lib/pdf/coords';
import { useObservationStore } from '@/lib/stores/observationStore';
import type { SectionInfo } from '@/lib/types';

import { ObservationThread } from './ObservationThread';

interface ObservationsPanelProps {
  versionId: string;
  versionNumber: number;
  sections: SectionInfo[];
  /** reviewers/admins create observations; editors reply; viewers read */
  canCreate: boolean;
  canReply: boolean;
  /**
   * Whether the user may resolve a thread they did NOT open. The backend
   * (observations/services.py, `set_status`) allows resolving only to the
   * thread's author or to an admin — gating this on `canCreate` instead put an
   * enabled Resolve button in front of every reviewer, which then 403'd.
   */
  canResolveAny?: boolean;
  currentUserEmail?: string | null;
  onSelectAnchor?: (quads: NormalizedBBox[]) => void;
}

export function ObservationsPanel({
  versionId,
  versionNumber,
  sections,
  canCreate,
  canReply,
  canResolveAny = false,
  currentUserEmail,
  onSelectAnchor,
}: ObservationsPanelProps) {
  const t = useDict('observations');
  const common = useDict('common');
  const { toast } = useToast();
  const searchParams = useSearchParams();
  const focusedObservationId = searchParams?.get('observation') ?? null;
  const items = useObservationStore((s) => s.items);
  const activeVersionId = useObservationStore((s) => s.versionId);
  const activeFilter = useObservationStore((s) => s.statusFilter);
  const generation = useObservationStore((s) => s.generation);
  const nextCursor = useObservationStore((s) => s.nextCursor);
  const isLoading = useObservationStore((s) => s.isLoading);
  const error = useObservationStore((s) => s.loadError);
  const isSubmitting = useObservationStore((s) => s.isSubmitting);
  const fetch = useObservationStore((s) => s.fetch);
  const reset = useObservationStore((s) => s.reset);
  const loadMore = useObservationStore((s) => s.loadMore);
  const retryLoad = useObservationStore((s) => s.retryLoad);
  const create = useObservationStore((s) => s.create);
  const filterKey = `${versionId}:${focusedObservationId ?? ''}`;
  const [filterSelection, setFilterSelection] = useState({ key: filterKey, showResolved: !!focusedObservationId });
  const showResolved = filterSelection.key === filterKey ? filterSelection.showResolved : !!focusedObservationId;
  const [modalOpen, setModalOpen] = useState(false);
  const [body, setBody] = useState('');
  const [sectionKey, setSectionKey] = useState('');
  const filter = showResolved ? 'all' : 'active';
  const scopeMatches = activeVersionId === versionId && activeFilter === filter;

  useEffect(() => {
    void fetch(versionId, filter, focusedObservationId);
    return reset;
  }, [versionId, filter, focusedObservationId, fetch, reset]);

  const visible = scopeMatches ? items : [];

  const act = async (result: Promise<boolean>) => {
    const currentGeneration = useObservationStore.getState().generation;
    const ok = await result;
    if (useObservationStore.getState().generation !== currentGeneration) return false;
    toast(ok ? common.saved : (useObservationStore.getState().error ?? common.error),
      ok ? 'success' : 'error');
    return ok;
  };

  return (
    <section data-testid="observations-panel" className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-muted-foreground">{t.title}</h2>
        <label className="flex min-h-11 cursor-pointer items-center gap-1.5 text-xs text-muted-foreground">
          <input
            data-testid="show-resolved"
            type="checkbox"
            checked={showResolved}
            onChange={() => setFilterSelection({ key: filterKey, showResolved: !showResolved })}
          />
          {t.showResolved}
        </label>
      </div>

      {canCreate ? (
        <button
          data-testid="add-observation"
          className="min-h-11 self-start rounded-full border border-border px-4 py-1.5 text-sm hover:bg-accent disabled:opacity-50"
          disabled={!scopeMatches || isLoading}
          onClick={() => setModalOpen(true)}
          type="button"
        >
          {t.add}
        </button>
      ) : null}

      {isLoading || !scopeMatches ? <p role="status" className="text-xs text-muted-foreground">{common.loading}</p> : null}
      {scopeMatches && error ? (
        <div className="text-xs text-destructive">
          <p role="alert">{error}</p>
          <button
            data-testid="observations-retry"
            className="mt-1 inline-flex min-h-11 items-center text-primary hover:underline disabled:opacity-50"
            disabled={isLoading}
            onClick={() => void retryLoad()}
            type="button"
          >
            {common.retry}
          </button>
        </div>
      ) : null}

      {visible.length === 0 && scopeMatches && !isLoading && !error ? (
        <EmptyState title={t.empty} description={t.emptyBody} />
      ) : (
        <ol className="flex flex-col gap-3">
          {visible.map((item) => (
            <ObservationThread
              key={`${generation}:${item.public_id}`}
              item={item}
              versionId={versionId}
              versionNumber={versionNumber}
              canReply={canReply}
              canResolveAny={canResolveAny}
              currentUserEmail={currentUserEmail}
              act={act}
              onSelectAnchor={onSelectAnchor}
            />
          ))}
        </ol>
      )}

      {scopeMatches && nextCursor ? (
        <button
          data-testid="observations-more"
          className="min-h-11 self-start rounded-full border border-border px-4 py-1.5 text-sm hover:bg-accent disabled:opacity-50"
          disabled={isLoading}
          onClick={() => void loadMore()}
          type="button"
        >
          {isLoading ? common.loading : t.loadMore}
        </button>
      ) : null}

      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title={t.addTitle}>
        <label className="block text-sm">
          <span className="text-muted-foreground">{t.section}</span>
          <select
            data-testid="observation-section"
            className="mt-1 min-h-11 w-full rounded-lg border border-border bg-background px-3 py-2 text-base sm:text-sm"
            value={sectionKey}
            onChange={(event) => setSectionKey(event.target.value)}
          >
            <option value="">—</option>
            {sections.map((section) => (
              <option key={section.stable_key} value={section.stable_key}>
                {section.heading_text}
              </option>
            ))}
          </select>
        </label>
        <label className="mt-3 block text-sm">
          <span className="text-muted-foreground">{t.body}</span>
          <textarea
            data-testid="observation-body"
            className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-base sm:text-sm"
            rows={3}
            value={body}
            onChange={(event) => setBody(event.target.value)}
          />
        </label>
        <div className="mt-4 flex justify-end gap-2">
          <button
            className="min-h-11 rounded-full border border-border px-4 py-2 text-sm"
            onClick={() => setModalOpen(false)}
            type="button"
          >
            {common.cancel}
          </button>
          <button
            data-testid="observation-submit"
            className="min-h-11 rounded-full bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-50"
            disabled={!body.trim() || isSubmitting}
            onClick={() =>
              void act(create(versionId, { body: body.trim(), sectionKey })).then((ok) => {
                if (ok) {
                  setModalOpen(false);
                  setBody('');
                  setSectionKey('');
                }
              })
            }
            type="button"
          >
            {t.submit}
          </button>
        </div>
      </Modal>
    </section>
  );
}
