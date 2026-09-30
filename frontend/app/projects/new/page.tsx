'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';

import { useToast } from '@/components/ui/toast';
import { useDict } from '@/lib/i18n/dictionaries';
import { useRequireAuth } from '@/lib/hooks/useRequireAuth';
import { api } from '@/lib/services/http';
import { maybeShowUpgradeDialog } from '@/lib/stores/upgradeDialogStore';
import { useOrgStore } from '@/lib/stores/orgStore';

export default function NewProjectPage() {
  const { isAuthenticated } = useRequireAuth();
  const router = useRouter();
  const t = useDict('projects');
  const common = useDict('common');
  const { toast } = useToast();
  const activeOrgId = useOrgStore((s) => s.activeOrgId);
  const fetchOrgs = useOrgStore((s) => s.fetchOrgs);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (isAuthenticated) void fetchOrgs();
  }, [isAuthenticated, fetchOrgs]);

  if (!isAuthenticated) return null;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    if (!name.trim()) {
      setError(t.nameRequired);
      return;
    }
    setIsSubmitting(true);
    // The org list may still be in flight on a cold load: resolve it inline
    // instead of silently dropping the submit.
    let orgId = activeOrgId;
    if (!orgId) {
      await fetchOrgs();
      orgId = useOrgStore.getState().activeOrgId;
    }
    if (!orgId) {
      setError(common.error);
      setIsSubmitting(false);
      return;
    }
    try {
      const { data } = await api.post(`orgs/${orgId}/projects/`, {
        name: name.trim(),
        description: description.trim(),
      });
      toast(common.saved, 'success');
      router.push(`/projects/${data.public_id}`);
    } catch (err) {
      if (maybeShowUpgradeDialog(err)) {
        setIsSubmitting(false);
        return;
      }
      setError(
        (err as { response?: { data?: { error?: string } } })?.response?.data?.error ??
          common.error
      );
      setIsSubmitting(false);
    }
  };

  return (
    <main className="mx-auto max-w-xl px-6 py-10">
      <h1 className="text-2xl font-semibold">{t.newProject}</h1>
      <form className="mt-6 flex flex-col gap-4" onSubmit={submit}>
        <label className="block text-sm">
          <span className="text-muted-foreground">{t.name}</span>
          <input
            data-testid="project-name"
            className="mt-1 min-h-11 w-full rounded-lg border border-border bg-background px-3 py-2 text-base sm:text-sm"
            value={name}
            onChange={(event) => setName(event.target.value)}
            autoFocus
          />
        </label>
        <label className="block text-sm">
          <span className="text-muted-foreground">{t.description}</span>
          <textarea
            data-testid="project-description"
            className="mt-1 min-h-11 w-full rounded-lg border border-border bg-background px-3 py-2 text-base sm:text-sm"
            rows={3}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
        <button
          data-testid="project-submit"
          className="min-h-11 rounded-full bg-primary px-5 py-2.5 text-sm text-primary-foreground disabled:opacity-50"
          disabled={isSubmitting}
          type="submit"
        >
          {isSubmitting ? t.creating : t.createCta}
        </button>
      </form>
    </main>
  );
}
