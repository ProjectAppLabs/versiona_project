'use client';

import { useDict } from '@/lib/i18n/dictionaries';
import { useObservationStore } from '@/lib/stores/observationStore';
import type { ObservationTextSummary } from '@/lib/types/observations';

interface ProgressiveObservationTextProps {
  summary: ObservationTextSummary;
  testId: string;
}

/** Reading more always loads one fragment; a long thread never expands itself. */
export function ProgressiveObservationText({ summary, testId }: ProgressiveObservationTextProps) {
  const t = useDict('observations');
  const common = useDict('common');
  const content = useObservationStore((state) => state.contents[summary.body_content_url]);
  const loadContent = useObservationStore((state) => state.loadContent);
  const hasMore = content?.isLoaded
    ? !content.eof
    : summary.body_length > Array.from(summary.body_preview).length;

  return (
    <div className="min-w-0">
      <p data-testid={testId} className="whitespace-pre-wrap text-sm [overflow-wrap:anywhere]">
        {content?.isLoaded ? content.content : summary.body_preview}
      </p>
      {content?.error ? <p role="alert" className="mt-1 text-xs text-destructive">{content.error}</p> : null}
      {hasMore ? (
        <button
          data-testid={`${testId}-more`}
          className="mt-1 text-xs text-primary underline-offset-2 hover:underline disabled:opacity-50"
          disabled={content?.isLoading}
          onClick={() => void loadContent(summary.body_content_url)}
          type="button"
        >
          {content?.isLoading ? common.loading : content?.error ? common.retry : t.loadMoreText}
        </button>
      ) : null}
    </div>
  );
}
