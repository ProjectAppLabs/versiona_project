'use client';

/** B4 — archive / trash the project (admin). T4 is enforced server-side:
 * with seals the delete is rejected and only archiving remains. */

import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';

import { TypeToConfirmDialog } from '@/components/ui/TypeToConfirmDialog';
import { useToast } from '@/components/ui/toast';
import { useDict } from '@/lib/i18n/dictionaries';
import { api } from '@/lib/services/http';

interface ProjectInfo {
  name: string;
  status: 'active' | 'archived';
  effective_role: string | null;
}

export function ProjectAdminActions({ projectId }: { projectId: string }) {
  const t = useDict('projectActions');
  const common = useDict('common');
  const { toast } = useToast();
  const router = useRouter();
  const [project, setProject] = useState<ProjectInfo | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get(`projects/${projectId}/`);
      setProject(data);
    } catch {
      setProject(null);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!project || project.effective_role !== 'admin') return null;

  const archiveToggle = async () => {
    const action = project.status === 'archived' ? 'unarchive' : 'archive';
    try {
      await api.post(`projects/${projectId}/${action}/`);
      toast(common.saved, 'success');
      void load();
    } catch (err) {
      toast(
        (err as { response?: { data?: { error?: string } } })?.response?.data?.error ??
          common.error,
        'error'
      );
    }
  };

  return (
    <section data-testid="project-admin-actions" className="mt-10 rounded-2xl border border-border bg-card p-4">
      {project.status === 'archived' ? (
        <p data-testid="archived-banner" className="mb-3 text-sm text-muted-foreground">
          {t.archived}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <button
          data-testid="archive-project"
          className="min-h-11 rounded-full border border-border px-4 py-2 text-sm hover:bg-accent"
          onClick={() => void archiveToggle()}
          type="button"
        >
          {project.status === 'archived' ? t.unarchive : t.archive}
        </button>
        <button
          data-testid="trash-project"
          className="min-h-11 rounded-full border border-destructive/50 px-4 py-2 text-sm text-destructive hover:bg-destructive/10"
          onClick={() => setConfirmOpen(true)}
          type="button"
        >
          {t.trash}
        </button>
      </div>

      <TypeToConfirmDialog
        open={confirmOpen}
        title={t.trashTitle}
        description={t.trashBody}
        expectedText={project.name}
        confirmLabel={common.delete}
        cancelLabel={common.cancel}
        onClose={() => setConfirmOpen(false)}
        onConfirm={async () => {
          try {
            await api.delete(`projects/${projectId}/`, {
              data: { confirm_name: project.name },
            });
            setConfirmOpen(false);
            toast(common.saved, 'success');
            router.push('/projects');
          } catch (err) {
            setConfirmOpen(false);
            toast(
              (err as { response?: { data?: { error?: string } } })?.response?.data?.error ??
                t.onlyArchivable,
              'error'
            );
          }
        }}
      />
    </section>
  );
}
