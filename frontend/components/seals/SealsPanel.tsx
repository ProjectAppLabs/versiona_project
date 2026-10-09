'use client';

/**
 * Seals panel (D4/D5 — docs/plan/04 §2): every seal with its validity state,
 * the evidence of WHY, offline-verifiable signature check, and the
 * coordinator's pending plan when the project runs in that mode.
 */

import { useEffect, useState } from 'react';

import { InvalidationReviewCard } from '@/components/seals/InvalidationReviewCard';
import { EmptyState } from '@/components/ui/EmptyState';
import { Skeleton } from '@/components/ui/Skeleton';
import { StatusBadge, type StatusBadgeVariant } from '@/components/ui/StatusBadge';
import { useToast } from '@/components/ui/toast';
import { useDict } from '@/lib/i18n/dictionaries';
import { useSealStore, type SealSummary, type ValidityRecord } from '@/lib/stores/sealStore';

const DECISION_VARIANT: Record<string, StatusBadgeVariant> = {
  preserved: 'approved',
  invalidated: 'failed',
  pending_confirmation: 'in_review',
  superseded: 'neutral',
};

function formatDate(iso: string | null) {
  if (!iso) return '';
  return new Intl.DateTimeFormat('es', { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(iso)
  );
}

interface SealsPanelProps {
  versionId: string;
  canConfirmPlan: boolean;
  currentUserEmail?: string | null;
  onWithdraw?: (seal: SealSummary) => void;
}

export function SealsPanel({ versionId, canConfirmPlan, currentUserEmail, onWithdraw }: SealsPanelProps) {
  const t = useDict('seals');
  const { toast } = useToast();
  const seals = useSealStore((s) => s.seals);
  const validityRecords = useSealStore((s) => s.validityRecords);
  const pendingPlan = useSealStore((s) => s.pendingPlan);
  const isLoading = useSealStore((s) => s.isLoading);
  const fetchSeals = useSealStore((s) => s.fetchSeals);
  const fetchPlan = useSealStore((s) => s.fetchPlan);
  const verifySeal = useSealStore((s) => s.verifySeal);
  const [verified, setVerified] = useState<Record<string, boolean>>({});

  useEffect(() => {
    void fetchSeals(versionId);
    void fetchPlan(versionId);
  }, [versionId, fetchSeals, fetchPlan]);

  const verify = async (seal: SealSummary) => {
    const result = await verifySeal(versionId, seal.public_id);
    if (result) {
      setVerified((current) => ({ ...current, [seal.public_id]: result.signature_valid }));
      toast(result.signature_valid ? t.signatureValid : t.signatureInvalid,
        result.signature_valid ? 'success' : 'error');
    }
  };

  const recordFor = (record: ValidityRecord) => {
    const variant = DECISION_VARIANT[record.decision] ?? 'neutral';
    const reason = t.reason[record.reason_code as keyof typeof t.reason] ?? record.reason_code;
    return { variant, reason };
  };

  if (isLoading && seals.length === 0) {
    return <Skeleton className="h-40 w-full" data-testid="seals-loading" />;
  }

  return (
    <section data-testid="seals-panel" className="flex flex-col gap-3">
      <h2 className="text-sm font-semibold text-muted-foreground">{t.title}</h2>

      {canConfirmPlan && pendingPlan.length > 0 ? (
        <InvalidationReviewCard versionId={versionId} pending={pendingPlan} />
      ) : null}

      {seals.length === 0 && validityRecords.length === 0 ? (
        <EmptyState title={t.empty} description={t.emptyBody} data-testid="seals-empty" />
      ) : null}

      {/* Seals PLACED on this version */}
      {seals.map((seal) => (
        <article
          key={seal.public_id}
          data-testid={`seal-${seal.reviewer_email}`}
          className="rounded-2xl border border-border bg-card p-4"
        >
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{seal.reviewer_email}</span>
            <StatusBadge variant={seal.is_active ? 'approved' : 'neutral'}>
              {seal.is_active ? t.validity.valid : t.validity.revoked}
            </StatusBadge>
            {verified[seal.public_id] !== undefined ? (
              <StatusBadge variant={verified[seal.public_id] ? 'approved' : 'failed'}>
                Ed25519 {verified[seal.public_id] ? '✓' : '✗'}
              </StatusBadge>
            ) : null}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {t.covers}{' '}
            {seal.covers_all
              ? t.allDocument
              : `${seal.covered_keys.length} ${t.sections}: ${seal.covered_keys.join(', ')}`}
            {' · '}
            {formatDate(seal.created_at)}
          </p>
          <div className="mt-2 flex gap-3 text-xs">
            <button
              data-testid={`verify-${seal.public_id}`}
              className="inline-flex min-h-11 items-center text-primary underline-offset-2 hover:underline"
              onClick={() => void verify(seal)}
              type="button"
            >
              {t.verify}
            </button>
            {onWithdraw && seal.is_active && seal.reviewer_email === currentUserEmail ? (
              <button
                data-testid="withdraw-seal"
                className="inline-flex min-h-11 items-center text-destructive underline-offset-2 hover:underline"
                onClick={() => onWithdraw(seal)}
                type="button"
              >
                {t.withdraw}
              </button>
            ) : null}
          </div>
        </article>
      ))}

      {/* What D5 decided about the PREVIOUS version's seals */}
      {validityRecords.map((record) => {
        const { variant, reason } = recordFor(record);
        return (
          <article
            key={`${record.seal.public_id}-${record.to_version}`}
            data-testid={`validity-${record.seal.reviewer_email}`}
            data-decision={record.decision}
            className="rounded-2xl border border-border bg-muted/30 p-4"
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm">
                {t.sealed} v{record.seal.version_number} · {record.seal.reviewer_email}
              </span>
              <StatusBadge variant={variant}>
                {t.validity[record.decision as keyof typeof t.validity]}
              </StatusBadge>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{reason}</p>
            {record.evidence.changed?.length ? (
              <p className="mt-1 text-xs">
                <span className="text-muted-foreground">{t.changedSections}: </span>
                {record.evidence.changed.map((c) => c.stable_key).join(', ')}
              </p>
            ) : null}
            {record.evidence.still_intact?.length ? (
              <p className="mt-1 text-xs">
                <span className="text-muted-foreground">{t.stillIntact}: </span>
                {record.evidence.still_intact.map((c) => c.stable_key).join(', ')}
              </p>
            ) : null}
            {record.decided_by_email ? (
              <p className="mt-1 text-xs text-muted-foreground">
                {record.decided_mode}: {record.decided_by_email} · {formatDate(record.decided_at)}
              </p>
            ) : null}
          </article>
        );
      })}
    </section>
  );
}
