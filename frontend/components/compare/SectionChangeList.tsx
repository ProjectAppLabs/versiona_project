'use client';

/** Modified-sections list with direct access (E1 view 2). */

import { StatusBadge, type StatusBadgeVariant } from '@/components/ui/StatusBadge';
import { useDict } from '@/lib/i18n/dictionaries';
import { displayHeading, isChanged, type SectionChange } from '@/lib/compare/sync';

const VARIANT: Record<SectionChange['change_type'], StatusBadgeVariant> = {
  unchanged: 'neutral',
  modified: 'in_review',
  added: 'approved',
  removed: 'failed',
  renamed_only: 'draft',
};

interface SectionChangeListProps {
  changes: SectionChange[];
  activeKey: string | null;
  hideUnchanged: boolean;
  onToggleHideUnchanged: () => void;
  onSelect: (key: string) => void;
}

export function SectionChangeList({
  changes,
  activeKey,
  hideUnchanged,
  onToggleHideUnchanged,
  onSelect,
}: SectionChangeListProps) {
  const t = useDict('compare');
  const visible = hideUnchanged ? changes.filter(isChanged) : changes;

  return (
    <div>
      <label className="mb-2 flex min-h-11 cursor-pointer items-center gap-2 text-xs text-muted-foreground">
        <input
          data-testid="hide-unchanged"
          type="checkbox"
          checked={hideUnchanged}
          onChange={onToggleHideUnchanged}
        />
        {t.hideUnchanged}
      </label>
      <ol data-testid="section-change-list" className="flex flex-col gap-2">
        {visible.map((change) => (
          <li key={change.stable_key}>
            <button
              data-testid={`section-${change.stable_key}`}
              data-change={change.change_type}
              aria-current={activeKey === change.stable_key}
              className={`flex min-h-11 w-full items-center justify-between gap-2 rounded-lg border px-3 py-2 text-left text-sm transition-colors ${
                activeKey === change.stable_key
                  ? 'border-primary bg-primary/5'
                  : 'border-border bg-card hover:bg-accent'
              }`}
              onClick={() => onSelect(change.stable_key)}
              type="button"
            >
              {/* The heading wraps: in the 260 px side column a `truncate`
                  cut every changed section of the reference contract (TIP-2). */}
              <span className="min-w-0 [overflow-wrap:anywhere]">{displayHeading(change)}</span>
              <span className="flex shrink-0">
                <StatusBadge variant={VARIANT[change.change_type]}>
                  {t.change[change.change_type]}
                </StatusBadge>
              </span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}
