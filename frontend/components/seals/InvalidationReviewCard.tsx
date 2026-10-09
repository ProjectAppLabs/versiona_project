'use client';

/** Coordinator's pending plan (D5 coordinator mode): one decision per seal,
 * with the engine's proposal pre-selected and the evidence in sight. */

import { useState } from 'react';

import { StatusBadge } from '@/components/ui/StatusBadge';
import { useToast } from '@/components/ui/toast';
import { useDict } from '@/lib/i18n/dictionaries';
import { useSealStore, type ValidityRecord } from '@/lib/stores/sealStore';

interface InvalidationReviewCardProps {
  versionId: string;
  pending: ValidityRecord[];
}

export function InvalidationReviewCard({ versionId, pending }: InvalidationReviewCardProps) {
  const t = useDict('seals');
  const { toast } = useToast();
  const confirmPlan = useSealStore((s) => s.confirmPlan);
  const isSubmitting = useSealStore((s) => s.isSubmitting);
  const [choices, setChoices] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      pending.map((record) => [
        record.seal.public_id,
        record.proposed_decision === 'preserved' ? 'preserved' : 'invalidated',
      ])
    )
  );

  const submit = async () => {
    const ok = await confirmPlan(versionId, choices);
    toast(ok ? t.confirmPlan + ' ✓' : useSealStore.getState().error ?? 'Error',
      ok ? 'success' : 'error');
  };

  return (
    <div
      data-testid="invalidation-review-card"
      className="rounded-2xl border border-amber-500/50 bg-amber-500/5 p-4"
    >
      <h3 className="font-medium">{t.planTitle}</h3>
      <p className="mt-1 text-xs text-muted-foreground">{t.planBody}</p>
      <ul className="mt-3 flex flex-col gap-3">
        {pending.map((record) => (
          <li
            key={record.seal.public_id}
            data-testid={`plan-item-${record.seal.reviewer_email}`}
            className="rounded-xl border border-border bg-card p-3"
          >
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span>
                {record.seal.reviewer_email} — v{record.seal.version_number}
              </span>
              <StatusBadge variant={record.proposed_decision === 'preserved' ? 'approved' : 'failed'}>
                {t.proposed}: {t.validity[record.proposed_decision as keyof typeof t.validity]}
              </StatusBadge>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              {t.reason[record.reason_code as keyof typeof t.reason] ?? record.reason_code}
              {record.evidence.changed?.length
                ? ` · ${record.evidence.changed.map((c) => c.stable_key).join(', ')}`
                : ''}
            </p>
            <div className="mt-2 flex gap-4 text-sm">
              {(['preserved', 'invalidated'] as const).map((option) => (
                <label key={option} className="flex min-h-11 cursor-pointer items-center gap-1.5">
                  <input
                    data-testid={`plan-${option}-${record.seal.public_id}`}
                    type="radio"
                    name={`plan-${record.seal.public_id}`}
                    checked={choices[record.seal.public_id] === option}
                    onChange={() =>
                      setChoices((current) => ({
                        ...current,
                        [record.seal.public_id]: option,
                      }))
                    }
                  />
                  {option === 'preserved' ? t.keep : t.invalidate}
                </label>
              ))}
            </div>
          </li>
        ))}
      </ul>
      <button
        data-testid="confirm-plan"
        className="mt-3 min-h-11 rounded-full bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-50"
        disabled={isSubmitting}
        onClick={() => void submit()}
        type="button"
      >
        {t.confirmPlan}
      </button>
    </div>
  );
}
