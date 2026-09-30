'use client';

/** B3: project configuration editor — every save creates a NEW config version
 * (I8: existing document versions keep their pinned config). Admin-only. */

import { useParams } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';

import { AsyncBoundary } from '@/components/ui/AsyncBoundary';
import { useToast } from '@/components/ui/toast';
import { interpolate, useDict } from '@/lib/i18n/dictionaries';
import { useRequireAuth } from '@/lib/hooks/useRequireAuth';
import { api } from '@/lib/services/http';
import { useOrgStore } from '@/lib/stores/orgStore';
import { useReviewStore } from '@/lib/stores/reviewStore';
import { MembersSection } from '@/components/projects/MembersSection';

interface CheckItem {
  key: string;
  label: string;
  type: 'required_section' | 'required_text' | 'forbidden_text';
  param: string;
  severity: 'fail' | 'warn';
}

interface ConfigResponse {
  number: number;
  d5_mode: 'auto' | 'coordinator';
  approval_policy: { required: number | string };
  checklist: CheckItem[];
  section_owners: Record<string, number[]>;
}

interface TemplateRow {
  public_id: string;
  name: string;
  items: CheckItem[];
}

export default function ProjectSettingsPage() {
  const { isAuthenticated } = useRequireAuth();
  const params = useParams<{ projectId: string }>();
  const t = useDict('projectConfig');
  const common = useDict('common');
  const { toast } = useToast();
  const fetchMembers = useReviewStore((s) => s.fetchMembers);
  const activeOrgId = useOrgStore((s) => s.activeOrgId);
  const fetchOrgs = useOrgStore((s) => s.fetchOrgs);

  const [config, setConfig] = useState<ConfigResponse | null>(null);
  const [templates, setTemplates] = useState<TemplateRow[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const { data } = await api.get<ConfigResponse>(`projects/${params.projectId}/config/`);
      setConfig(data);
    } catch (err) {
      setError(
        (err as { response?: { status?: number } })?.response?.status === 404
          ? 'La configuración del proyecto es una vista de administración.'
          : common.error
      );
    }
  }, [params.projectId, common.error]);

  useEffect(() => {
    if (!isAuthenticated) return;
    void load();
    void fetchMembers(params.projectId);
    void fetchOrgs();
  }, [isAuthenticated, load, fetchMembers, fetchOrgs, params.projectId]);

  useEffect(() => {
    if (!isAuthenticated || !activeOrgId) return;
    void api
      .get(`orgs/${activeOrgId}/checklist_templates/`)
      .then(({ data }) => setTemplates(data.results))
      .catch(() => undefined);
  }, [isAuthenticated, activeOrgId]);

  if (!isAuthenticated) return null;

  const setChecklist = (index: number, patch: Partial<CheckItem>) =>
    setConfig((current) =>
      current
        ? {
            ...current,
            checklist: current.checklist.map((item, i) =>
              i === index ? { ...item, ...patch } : item
            ),
          }
        : current
    );

  const save = async () => {
    if (!config) return;
    setIsSaving(true);
    try {
      const { data } = await api.post(`projects/${params.projectId}/config/`, {
        d5_mode: config.d5_mode,
        approval_policy: config.approval_policy,
        checklist: config.checklist,
        section_owners: config.section_owners,
      });
      toast(interpolate(t.saved, { n: data.number }), 'success');
      void load();
    } catch (err) {
      toast(
        (err as { response?: { data?: { error?: string } } })?.response?.data?.error ??
          common.error,
        'error'
      );
    } finally {
      setIsSaving(false);
    }
  };

  const applyTemplate = async () => {
    if (!selectedTemplate) return;
    try {
      const { data } = await api.post(`projects/${params.projectId}/config/apply_template/`, {
        template: selectedTemplate,
      });
      toast(interpolate(t.saved, { n: data.number }), 'success');
      void load();
    } catch {
      toast(common.error, 'error');
    }
  };

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <h1 className="text-2xl font-semibold">{t.title}</h1>
      <p className="mt-1 text-sm text-muted-foreground">{t.subtitle}</p>

      <div className="mt-6">
        <AsyncBoundary
          isLoading={!config && !error}
          error={error}
          onRetry={() => void load()}
          retryLabel={common.retry}
        >
          {config ? (
            <div className="flex flex-col gap-6" data-testid="project-config">
              <p className="text-xs text-muted-foreground">
                {interpolate(t.currentVersion, { n: config.number })}
              </p>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <label className="block text-sm">
                  <span className="text-muted-foreground">{t.d5Mode}</span>
                  <select
                    data-testid="config-d5-mode"
                    className="mt-1 min-h-11 w-full rounded-lg border border-border bg-background px-3 py-2 text-base sm:text-sm"
                    value={config.d5_mode}
                    onChange={(event) =>
                      setConfig({ ...config, d5_mode: event.target.value as 'auto' | 'coordinator' })
                    }
                  >
                    <option value="auto">{t.d5Auto}</option>
                    <option value="coordinator">{t.d5Coordinator}</option>
                  </select>
                </label>
                <label className="block text-sm">
                  <span className="text-muted-foreground">{t.approval}</span>
                  <select
                    data-testid="config-approval"
                    className="mt-1 min-h-11 w-full rounded-lg border border-border bg-background px-3 py-2 text-base sm:text-sm"
                    value={String(config.approval_policy.required ?? 1)}
                    onChange={(event) =>
                      setConfig({
                        ...config,
                        approval_policy: {
                          required:
                            event.target.value === 'all_assigned'
                              ? 'all_assigned'
                              : Number(event.target.value),
                        },
                      })
                    }
                  >
                    <option value="1">{t.approvalOne}</option>
                    <option value="all_assigned">{t.approvalOwners}</option>
                  </select>
                </label>
              </div>

              <section>
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-semibold">{t.checklist}</h2>
                  <button
                    data-testid="add-check"
                    className="min-h-11 rounded-full border border-border px-3 py-1.5 text-sm hover:bg-accent"
                    onClick={() =>
                      setConfig({
                        ...config,
                        checklist: [
                          ...config.checklist,
                          {
                            key: `check-${config.checklist.length + 1}-${Date.now() % 10000}`,
                            label: '',
                            type: 'required_text',
                            param: '',
                            severity: 'fail',
                          },
                        ],
                      })
                    }
                    type="button"
                  >
                    {t.addCheck}
                  </button>
                </div>
                <ol className="mt-2 flex flex-col gap-2">
                  {config.checklist.map((item, index) => (
                    <li
                      key={item.key}
                      className="grid grid-cols-1 gap-2 rounded-xl border border-border bg-card p-3 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)_auto_auto]"
                    >
                      <input
                        data-testid={`check-label-${index}`}
                        className="min-h-11 min-w-0 rounded-lg border border-border bg-background px-2 py-1.5 text-base sm:text-sm"
                        placeholder={t.checkLabel}
                        aria-label={t.checkLabel}
                        value={item.label}
                        onChange={(event) => setChecklist(index, { label: event.target.value })}
                      />
                      <select
                        data-testid={`check-type-${index}`}
                        aria-label={t.checkType}
                        className="min-h-11 min-w-0 rounded-lg border border-border bg-background px-2 py-1.5 text-base sm:text-sm"
                        value={item.type}
                        onChange={(event) =>
                          setChecklist(index, { type: event.target.value as CheckItem['type'] })
                        }
                      >
                        <option value="required_section">{t.typeRequiredSection}</option>
                        <option value="required_text">{t.typeRequiredText}</option>
                        <option value="forbidden_text">{t.typeForbiddenText}</option>
                      </select>
                      <input
                        data-testid={`check-param-${index}`}
                        className="min-h-11 min-w-0 rounded-lg border border-border bg-background px-2 py-1.5 text-base sm:text-sm"
                        placeholder={t.checkParam}
                        aria-label={t.checkParam}
                        value={item.param}
                        onChange={(event) => setChecklist(index, { param: event.target.value })}
                      />
                      <select
                        aria-label={t.checkSeverity}
                        className="min-h-11 min-w-0 rounded-lg border border-border bg-background px-2 py-1.5 text-base sm:text-sm"
                        value={item.severity}
                        onChange={(event) =>
                          setChecklist(index, {
                            severity: event.target.value as CheckItem['severity'],
                          })
                        }
                      >
                        <option value="fail">{t.severityFail}</option>
                        <option value="warn">{t.severityWarn}</option>
                      </select>
                      <button
                        aria-label={t.remove}
                        className="min-h-11 min-w-11 text-sm text-destructive underline-offset-2 hover:underline"
                        onClick={() =>
                          setConfig({
                            ...config,
                            checklist: config.checklist.filter((_, i) => i !== index),
                          })
                        }
                        type="button"
                      >
                        {t.remove}
                      </button>
                    </li>
                  ))}
                </ol>
              </section>

              {templates.length > 0 ? (
                <section className="flex flex-wrap items-end gap-2">
                  <label className="block min-w-0 flex-1 text-sm">
                    <span className="text-muted-foreground">{t.applyTemplate}</span>
                    <select
                      data-testid="template-select"
                      className="mt-1 min-h-11 w-full rounded-lg border border-border bg-background px-3 py-2 text-base sm:text-sm"
                      value={selectedTemplate}
                      onChange={(event) => setSelectedTemplate(event.target.value)}
                    >
                      <option value="">—</option>
                      {templates.map((template) => (
                        <option key={template.public_id} value={template.public_id}>
                          {template.name} ({template.items.length})
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    className="min-h-11 rounded-full border border-border px-4 py-2 text-sm hover:bg-accent"
                    disabled={!selectedTemplate}
                    onClick={() => void applyTemplate()}
                    type="button"
                  >
                    {t.apply}
                  </button>
                </section>
              ) : null}

              <button
                data-testid="save-config"
                className="min-h-11 self-start rounded-full bg-primary px-5 py-2.5 text-sm text-primary-foreground disabled:opacity-50"
                disabled={isSaving}
                onClick={() => void save()}
                type="button"
              >
                {interpolate(t.save, { n: config.number + 1 })}
              </button>
            </div>
          ) : null}
        </AsyncBoundary>
      </div>

      {config ? <MembersSection projectId={params.projectId} /> : null}
    </main>
  );
}
