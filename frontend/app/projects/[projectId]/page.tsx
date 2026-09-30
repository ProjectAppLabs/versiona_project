'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useCallback } from 'react';

import { ActivityFeed } from '@/components/activity/ActivityFeed';
import { ProjectAdminActions } from '@/components/projects/ProjectAdminActions';
import { SavedComparisons } from '@/components/compare/SavedComparisons';
import { UploadDropzone } from '@/components/versions/UploadDropzone';
import { AsyncBoundary } from '@/components/ui/AsyncBoundary';
import { useDict } from '@/lib/i18n/dictionaries';
import { useListController } from '@/lib/hooks/useListController';
import { useRequireAuth } from '@/lib/hooks/useRequireAuth';
import { api } from '@/lib/services/http';
import type { DocumentSummary } from '@/lib/types';

export default function ProjectPage() {
  const { isAuthenticated } = useRequireAuth();
  const params = useParams<{ projectId: string }>();
  const projectId = params.projectId;
  const t = useDict('documents');
  const common = useDict('common');

  const fetcher = useCallback(
    async ({ page, search }: { page: number; search: string }) => {
      const { data } = await api.get(`projects/${projectId}/documents/`, {
        params: { page, q: search || undefined },
      });
      return data;
    },
    [projectId]
  );

  const list = useListController<DocumentSummary>(fetcher);

  if (!isAuthenticated) return null;

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">{t.title}</h1>
        <div className="flex min-w-0 flex-wrap items-center gap-2">
        <Link
          data-testid="project-settings-link"
          className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-full border border-border px-4 py-2 text-sm hover:bg-accent"
          href={`/projects/${projectId}/settings`}
        >
          ⚙
        </Link>
        <input
          data-testid="documents-search"
          className="min-h-11 w-56 max-w-full rounded-full border border-border bg-background px-4 py-2 text-base sm:text-sm"
          placeholder={common.search}
          value={list.search}
          onChange={(event) => list.setSearch(event.target.value)}
        />
        </div>
      </div>

      <div className="mt-6 flex flex-col gap-6">
        <UploadDropzone projectId={projectId} compact onUploaded={list.reload} />

        <AsyncBoundary
          isLoading={list.isLoading}
          error={list.error}
          isEmpty={list.isEmpty}
          onRetry={list.retry}
          retryLabel={common.retry}
          emptyTitle={t.emptyTitle}
          emptyDescription={t.emptyBody}
        >
          <ul data-testid="documents-list" className="flex flex-col gap-3">
            {list.items.map((document) => (
              <li key={document.public_id}>
                <Link
                  className="flex items-center gap-4 rounded-2xl border border-border bg-card p-4 transition-shadow hover:shadow-md"
                  href={`/projects/${projectId}/documents/${document.public_id}`}
                >
                  {document.latest_version?.thumb_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={document.latest_version.thumb_url}
                      alt=""
                      className="h-16 w-12 rounded-md border border-border object-cover"
                    />
                  ) : (
                    <div className="flex h-16 w-12 items-center justify-center rounded-md border border-border bg-muted text-[10px] text-muted-foreground">
                      PDF
                    </div>
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="break-words font-medium [overflow-wrap:anywhere]">{document.title}</p>
                    <p className="text-xs text-muted-foreground">
                      {t.version} v{document.latest_number}
                      {document.latest_version?.message
                        ? ` · ${document.latest_version.message}`
                        : ''}
                    </p>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </AsyncBoundary>

        <SavedComparisons projectId={projectId} />
        <ProjectAdminActions projectId={projectId} />
        <ActivityFeed projectId={projectId} />
      </div>
    </main>
  );
}
