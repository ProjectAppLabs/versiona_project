'use client';

/**
 * Document timeline (flow C3 — docs/audit/03 §9): version cards with author,
 * date (user timezone), message (editable while draft — I2b), traffic-light
 * placeholder, thumbnail, tombstones for trashed versions (C4) and the
 * approved badge.
 */

import Link from 'next/link';
import { useState } from 'react';

import { StatusBadge } from '@/components/ui/StatusBadge';
import { TypeToConfirmDialog } from '@/components/ui/TypeToConfirmDialog';
import { useToast } from '@/components/ui/toast';
import { interpolate, useDict } from '@/lib/i18n/dictionaries';
import { useUpgradeDialogStore } from '@/lib/stores/upgradeDialogStore';
import { useVersionStore } from '@/lib/stores/versionStore';
import type { VersionSummary } from '@/lib/types';

interface VersionTimelineProps {
  projectId: string;
  documentId: string;
  versions: VersionSummary[];
  canEdit: boolean;
  onChanged: () => void;
  /** C3-A01: selection of two versions to compare (E1 entry point). */
  selected?: string[];
  onToggleSelect?: (versionId: string) => void;
}

function formatDate(iso: string) {
  try {
    return new Intl.DateTimeFormat('es', { dateStyle: 'medium', timeStyle: 'short' }).format(
      new Date(iso)
    );
  } catch {
    return iso;
  }
}

export function VersionTimeline({
  projectId,
  documentId,
  versions,
  canEdit,
  onChanged,
  selected = [],
  onToggleSelect,
}: VersionTimelineProps) {
  const t = useDict('documents');
  const common = useDict('common');
  const { toast } = useToast();
  const editMessage = useVersionStore((s) => s.editMessage);
  const trashVersion = useVersionStore((s) => s.trashVersion);
  const downloadUrl = useVersionStore((s) => s.downloadUrl);
  const [editing, setEditing] = useState<string | null>(null);
  const [draftMessage, setDraftMessage] = useState('');
  const [confirmTrash, setConfirmTrash] = useState<VersionSummary | null>(null);

  const download = async (version: VersionSummary) => {
    const url = await downloadUrl(version.public_id);
    if (url) {
      window.open(url, '_blank', 'noopener');
      return;
    }
    // 402 plan locks open the upgrade dialog (store-side); every other
    // failure used to die silently — surface it.
    if (!useUpgradeDialogStore.getState().isOpen) {
      toast(useVersionStore.getState().error ?? common.error, 'error');
    }
  };

  const saveMessage = async (version: VersionSummary) => {
    const ok = await editMessage(version.public_id, draftMessage);
    if (ok) {
      toast(common.saved, 'success');
      setEditing(null);
      onChanged();
    } else {
      toast(t.messageFrozen, 'error');
    }
  };

  return (
    <ol data-testid="version-timeline" className="flex flex-col gap-3">
      {versions.map((version) => (
        <li
          key={version.public_id}
          data-testid={`version-item-${version.number}`}
          className={`rounded-2xl border p-4 ${
            version.is_trashed
              ? 'border-dashed border-border bg-muted/30 opacity-70'
              : 'border-border bg-card'
          }`}
        >
          {version.is_trashed ? (
            <p className="text-sm text-muted-foreground">
              v{version.number} — {t.deletedVersion}
            </p>
          ) : (
            <div className="flex flex-wrap items-start gap-4 sm:flex-nowrap">
              {onToggleSelect && version.analysis_status === 'ready' ? (
                // The label is the 44x44 touch target around the native checkbox,
                // centred on the 80 px thumbnail like the bare checkbox was.
                <label className="mt-[18px] inline-flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center">
                  <input
                    data-testid={`select-version-${version.number}`}
                    type="checkbox"
                    aria-label={`Seleccionar v${version.number} para comparar`}
                    className="h-5 w-5"
                    checked={selected.includes(version.public_id)}
                    onChange={() => onToggleSelect(version.public_id)}
                  />
                </label>
              ) : null}
              {version.thumb_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={version.thumb_url}
                  alt={`v${version.number}`}
                  className="h-20 w-14 rounded-md border border-border object-cover"
                />
              ) : (
                <div className="flex h-20 w-14 items-center justify-center rounded-md border border-border bg-muted text-xs text-muted-foreground">
                  PDF
                </div>
              )}
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold">v{version.number}</span>
                  {version.is_approved ? (
                    <StatusBadge variant="approved">{t.approved}</StatusBadge>
                  ) : version.is_draft ? (
                    <StatusBadge variant="draft">{t.draft}</StatusBadge>
                  ) : null}
                  <StatusBadge
                    variant={
                      version.analysis_status === 'ready'
                        ? 'approved'
                        : version.analysis_status === 'failed'
                          ? 'failed'
                          : 'in_review'
                    }
                  >
                    {version.analysis_status === 'ready'
                      ? t.analysisDone
                      : version.analysis_status === 'failed'
                        ? t.analysisFailed
                        : t.analyzing}
                  </StatusBadge>
                  <span className="text-xs text-muted-foreground">
                    {t.scenario[version.source_scenario]} · {version.page_count} {t.pages}
                  </span>
                  {version.check_summary ? (
                    <span
                      data-testid={`check-light-${version.number}`}
                      className="text-xs"
                      title="Checks del proyecto"
                    >
                      <span className="text-emerald-600">✓{version.check_summary.pass}</span>{' '}
                      {version.check_summary.warn ? (
                        <span className="text-amber-600">⚠{version.check_summary.warn}</span>
                      ) : null}{' '}
                      {version.check_summary.fail ? (
                        <span className="text-destructive">✗{version.check_summary.fail}</span>
                      ) : null}
                    </span>
                  ) : null}
                </div>
                {editing === version.public_id ? (
                  <div className="mt-2 flex flex-wrap gap-2">
                    <input
                      data-testid="edit-message-input"
                      className="min-h-11 w-full min-w-0 rounded-lg border border-border bg-background px-3 py-1.5 text-base sm:w-auto sm:flex-1 sm:text-sm"
                      value={draftMessage}
                      onChange={(event) => setDraftMessage(event.target.value)}
                    />
                    <button
                      className="min-h-11 rounded-full bg-primary px-3 py-1.5 text-xs text-primary-foreground"
                      onClick={() => void saveMessage(version)}
                      type="button"
                    >
                      {common.save}
                    </button>
                    <button
                      className="min-h-11 rounded-full border border-border px-3 py-1.5 text-xs"
                      onClick={() => setEditing(null)}
                      type="button"
                    >
                      {common.cancel}
                    </button>
                  </div>
                ) : (
                  // The message wraps instead of truncating, and the edit control
                  // sits beside it rather than inside the clipped line: at 412 px a
                  // `truncate` paragraph used to hide "Editar mensaje" entirely.
                  <div className="mt-1 flex flex-wrap items-center gap-x-2">
                    <p className="min-w-0 text-sm text-muted-foreground [overflow-wrap:anywhere]">
                      {version.message || '—'}
                    </p>
                    {canEdit && version.is_draft && !version.is_trashed ? (
                      <button
                        data-testid={`edit-message-${version.number}`}
                        className="inline-flex min-h-11 items-center text-xs text-primary underline-offset-2 hover:underline"
                        onClick={() => {
                          setEditing(version.public_id);
                          setDraftMessage(version.message);
                        }}
                        type="button"
                        title={t.editMessage}
                      >
                        {t.editMessage}
                      </button>
                    ) : null}
                  </div>
                )}
                <p className="mt-1 text-xs text-muted-foreground">
                  {version.author_email ?? '—'} · {formatDate(version.created_at)}
                </p>
                {version.analysis_status === 'failed' && version.error_detail ? (
                  <p role="alert" className="mt-1 text-xs text-destructive">
                    {version.error_detail}
                  </p>
                ) : null}
              </div>
              {/* Below sm the actions take their own row under the card text,
                  so the text column keeps its width; from sm on they stay the
                  right-hand column. Same items, same order. */}
              <div className="flex w-full flex-wrap items-center justify-end gap-2 sm:w-auto sm:shrink-0 sm:flex-col sm:items-end">
                <Link
                  className="inline-flex min-h-11 items-center px-2 text-xs text-primary underline-offset-2 hover:underline"
                  href={`/projects/${projectId}/documents/${documentId}/versions/${version.public_id}`}
                >
                  {t.viewer}
                </Link>
                <button
                  className="inline-flex min-h-11 items-center px-2 text-xs text-primary underline-offset-2 hover:underline"
                  onClick={() => void download(version)}
                  type="button"
                >
                  {t.download}
                </button>
                {canEdit && version.is_draft && !version.is_trashed ? (
                  <button
                    data-testid={`trash-version-${version.number}`}
                    className="inline-flex min-h-11 items-center px-2 text-xs text-destructive underline-offset-2 hover:underline"
                    onClick={() => setConfirmTrash(version)}
                    type="button"
                  >
                    {common.delete}
                  </button>
                ) : null}
              </div>
            </div>
          )}
        </li>
      ))}

      <TypeToConfirmDialog
        open={confirmTrash !== null}
        title={t.deleteVersionTitle}
        description={interpolate(t.deleteVersionBody, { n: confirmTrash?.number ?? 0 })}
        expectedText={`v${confirmTrash?.number ?? ''}`}
        confirmLabel={common.delete}
        cancelLabel={common.cancel}
        onClose={() => setConfirmTrash(null)}
        onConfirm={async () => {
          if (!confirmTrash) return;
          const ok = await trashVersion(confirmTrash.public_id);
          setConfirmTrash(null);
          if (ok) {
            toast(common.saved, 'success');
            onChanged();
          } else {
            // A rejected delete (e.g. the 409 "solo la última versión puede
            // eliminarse") used to close the dialog and show nothing at all,
            // leaving the user unable to tell a refusal from a success. The
            // store already captured the backend's message — surface it, same
            // as download() and saveMessage() above.
            toast(useVersionStore.getState().error ?? common.error, 'error');
          }
        }}
      />
    </ol>
  );
}
