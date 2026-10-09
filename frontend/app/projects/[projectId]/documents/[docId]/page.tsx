'use client';

import { useParams, useRouter } from 'next/navigation';
import { useCallback, useState } from 'react';

import { UploadDropzone } from '@/components/versions/UploadDropzone';
import { VersionTimeline } from '@/components/versions/VersionTimeline';
import { AsyncBoundary } from '@/components/ui/AsyncBoundary';
import { useDict } from '@/lib/i18n/dictionaries';
import { useListController } from '@/lib/hooks/useListController';
import { useRequireAuth } from '@/lib/hooks/useRequireAuth';
import { api } from '@/lib/services/http';
import type { VersionSummary } from '@/lib/types';

export default function DocumentTimelinePage() {
  const { isAuthenticated } = useRequireAuth();
  const params = useParams<{ projectId: string; docId: string }>();
  const router = useRouter();
  const t = useDict('documents');
  const common = useDict('common');
  const compareDict = useDict('compare');
  const [selected, setSelected] = useState<string[]>([]);

  const toggleSelect = (versionId: string) =>
    setSelected((current) => {
      if (current.includes(versionId)) return current.filter((id) => id !== versionId);
      // Keep at most two: the newest pick replaces the oldest.
      return current.length < 2 ? [...current, versionId] : [current[1], versionId];
    });

  const fetcher = useCallback(
    async ({ page }: { page: number; search: string }) => {
      const { data } = await api.get(`documents/${params.docId}/versions/`, {
        params: { page },
      });
      return data;
    },
    [params.docId]
  );

  const list = useListController<VersionSummary>(fetcher);

  if (!isAuthenticated) return null;

  const compareSelected = () => {
    if (selected.length !== 2) return;
    // Chronological order: the older version is the base (E1).
    const ordered = list.items
      .filter((version) => selected.includes(version.public_id))
      .sort((a, b) => a.number - b.number)
      .map((version) => version.public_id);
    router.push(
      `/projects/${params.projectId}/documents/${params.docId}/compare/${ordered[0]}/${ordered[1]}`
    );
  };

  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">{t.versions}</h1>
        <div className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">
            {selected.length === 2 ? '' : compareDict.pickTwo}
          </span>
          <button
            data-testid="compare-selected"
            className="min-h-11 rounded-full bg-primary px-4 py-2 text-sm text-primary-foreground disabled:cursor-not-allowed disabled:opacity-40"
            disabled={selected.length !== 2}
            onClick={compareSelected}
            type="button"
          >
            {compareDict.compareCta}
          </button>
        </div>
      </div>

      <div className="mt-6 flex flex-col gap-6">
        <UploadDropzone documentId={params.docId} compact onUploaded={list.reload} />

        <AsyncBoundary
          isLoading={list.isLoading}
          error={list.error}
          isEmpty={list.isEmpty}
          onRetry={list.retry}
          retryLabel={common.retry}
          emptyTitle={t.timelineEmpty}
        >
          <VersionTimeline
            projectId={params.projectId}
            documentId={params.docId}
            versions={list.items}
            canEdit
            onChanged={list.reload}
            selected={selected}
            onToggleSelect={toggleSelect}
          />
          {list.hasNext || list.hasPrevious ? (
            <div className="flex items-center justify-between text-sm text-muted-foreground">
              <button
                className="min-h-11 rounded-full border border-border px-4 py-1.5 disabled:opacity-40"
                disabled={!list.hasPrevious}
                onClick={list.previousPage}
                type="button"
              >
                {common.previous}
              </button>
              <span>
                {common.page} {list.page}
              </span>
              <button
                className="min-h-11 rounded-full border border-border px-4 py-1.5 disabled:opacity-40"
                disabled={!list.hasNext}
                onClick={list.nextPage}
                type="button"
              >
                {common.next}
              </button>
            </div>
          ) : null}
        </AsyncBoundary>
      </div>
    </main>
  );
}
