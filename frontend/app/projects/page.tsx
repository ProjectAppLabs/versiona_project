'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';

import { AsyncBoundary } from '@/components/ui/AsyncBoundary';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { useDict } from '@/lib/i18n/dictionaries';
import { useListController } from '@/lib/hooks/useListController';
import { useRequireAuth } from '@/lib/hooks/useRequireAuth';
import { api } from '@/lib/services/http';
import { useOrgStore } from '@/lib/stores/orgStore';
import type { ProjectSummary } from '@/lib/types';

export default function ProjectsBoardPage() {
  const { isAuthenticated } = useRequireAuth();
  const t = useDict('projects');
  const common = useDict('common');
  const activeOrgId = useOrgStore((s) => s.activeOrgId);
  const fetchOrgs = useOrgStore((s) => s.fetchOrgs);

  useEffect(() => {
    if (isAuthenticated) void fetchOrgs();
  }, [isAuthenticated, fetchOrgs]);

  const [statusFilter, setStatusFilter] = useState('');

  const fetcher = useCallback(
    async ({ page, search }: { page: number; search: string }) => {
      if (!activeOrgId) return { count: 0, next: null, previous: null, results: [] };
      const { data } = await api.get(`orgs/${activeOrgId}/projects/`, {
        params: { page, q: search || undefined, status: statusFilter || undefined },
      });
      return data;
    },
    [activeOrgId, statusFilter]
  );

  const list = useListController<ProjectSummary>(fetcher);

  if (!isAuthenticated) return null;

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">{t.title}</h1>
        <div className="flex w-full min-w-0 flex-wrap items-center gap-2 sm:w-auto">
          <select
            data-testid="board-status-filter"
            aria-label={t.status.active + '/' + t.status.archived}
            className="min-h-11 rounded-full border border-border bg-background px-3 py-2 text-base sm:text-sm"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
          >
            <option value="">{t.filterAll}</option>
            <option value="active">{t.status.active}</option>
            <option value="archived">{t.status.archived}</option>
          </select>
          <input
            data-testid="board-search"
            className="min-h-11 min-w-0 flex-[1_1_12rem] rounded-full border border-border bg-background px-4 py-2 text-base sm:w-56 sm:flex-none sm:text-sm"
            placeholder={t.searchHint}
            value={list.search}
            onChange={(event) => list.setSearch(event.target.value)}
          />
          <Link
            className="inline-flex min-h-11 items-center rounded-full bg-primary px-4 py-2 text-sm text-primary-foreground hover:bg-primary/90"
            href="/projects/new"
          >
            {t.newProject}
          </Link>
        </div>
      </div>

      <div className="mt-6">
        <AsyncBoundary
          isLoading={list.isLoading}
          error={list.error}
          isEmpty={list.isEmpty}
          onRetry={list.retry}
          retryLabel={common.retry}
          emptyTitle={t.emptyTitle}
          emptyDescription={t.emptyBody}
          emptyAction={
            <Link
              className="inline-flex min-h-11 items-center rounded-full bg-primary px-4 py-2 text-sm text-primary-foreground"
              href="/projects/new"
            >
              {t.createCta}
            </Link>
          }
        >
          <ul data-testid="projects-grid" className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {list.items.map((project) => (
              <li key={project.public_id}>
                <Link
                  className="block rounded-2xl border border-border bg-card p-5 transition-shadow hover:shadow-md"
                  href={`/projects/${project.public_id}`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h2 className="min-w-0 break-words font-semibold [overflow-wrap:anywhere]">{project.name}</h2>
                    <StatusBadge variant={project.status === 'archived' ? 'neutral' : 'in_review'}>
                      {t.status[project.status]}
                    </StatusBadge>
                  </div>
                  {project.description ? (
                    <p className="mt-1 break-words text-sm text-muted-foreground [overflow-wrap:anywhere]">
                      {project.description}
                    </p>
                  ) : null}
                  <p className="mt-3 text-xs text-muted-foreground">
                    {project.document_count} {t.documents}
                    {project.effective_role ? ` · ${t.role[project.effective_role]}` : ''}
                  </p>
                </Link>
              </li>
            ))}
          </ul>
          <div className="mt-6 flex items-center justify-between text-sm text-muted-foreground">
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
        </AsyncBoundary>
      </div>
    </main>
  );
}
