'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useState } from 'react';

import { StatusBadge, type StatusBadgeVariant } from '@/components/ui/StatusBadge';
import { interpolate, useDict } from '@/lib/i18n/dictionaries';
import type { NormalizedBBox } from '@/lib/pdf/coords';
import { useObservationStore } from '@/lib/stores/observationStore';
import type { ObservationRow } from '@/lib/types/observations';

import { ProgressiveObservationText } from './ProgressiveObservationText';

const STATUS_VARIANT: Record<ObservationRow['status'], StatusBadgeVariant> = {
  open: 'in_review', answered: 'draft', resolved: 'approved',
};

const ACTION_CLASS = 'rounded-full border border-border px-3 py-1.5 text-xs hover:bg-accent disabled:opacity-50';

function isQuads(value: unknown): value is NormalizedBBox[] {
  return Array.isArray(value) && value.every((quad) => quad &&
    ['page', 'x0', 'y0', 'x1', 'y1'].every((key) => Number.isFinite(quad[key])));
}

interface ObservationThreadProps {
  item: ObservationRow;
  versionId: string;
  versionNumber: number;
  canReply: boolean;
  canResolveAny: boolean;
  currentUserEmail?: string | null;
  act: (result: Promise<boolean>) => Promise<boolean>;
  onSelectAnchor?: (quads: NormalizedBBox[]) => void;
}

export function ObservationThread({
  item, versionId, versionNumber, canReply, canResolveAny, currentUserEmail, act, onSelectAnchor,
}: ObservationThreadProps) {
  const t = useDict('observations');
  const common = useDict('common');
  const pathname = usePathname();
  const replies = useObservationStore((state) => state.replies[item.public_id]);
  const anchors = useObservationStore((state) => state.anchors[item.public_id]);
  const busy = useObservationStore((state) => !!state.mutations[item.public_id]);
  const loadReplies = useObservationStore((state) => state.loadReplies);
  const loadAnchors = useObservationStore((state) => state.loadAnchors);
  const loadContent = useObservationStore((state) => state.loadContent);
  const reply = useObservationStore((state) => state.reply);
  const setStatus = useObservationStore((state) => state.setStatus);
  const anchor = item.current_anchor?.version_number === versionNumber ? item.current_anchor : null;
  const anchorContent = useObservationStore((state) => anchor ? state.contents[anchor.quads_content_url] : undefined);
  const [replyDraft, setReplyDraft] = useState('');
  const [showReplies, setShowReplies] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [anchorRequested, setAnchorRequested] = useState(false);
  const [anchorError, setAnchorError] = useState<string | null>(null);

  const selectAnchor = async () => {
    if (!anchor) return;
    const generation = useObservationStore.getState().generation;
    setAnchorRequested(true);
    setAnchorError(null);
    await loadContent(anchor.quads_content_url);
    if (useObservationStore.getState().generation !== generation) return;
    const loaded = useObservationStore.getState().contents[anchor.quads_content_url];
    if (!loaded?.eof) return;
    try {
      const quads: unknown = JSON.parse(loaded.content);
      if (!isQuads(quads)) throw new Error('Invalid anchor');
      onSelectAnchor?.(quads);
    } catch {
      setAnchorError(t.anchorLoadError);
    }
  };

  const visibleReplies = [...(replies?.items ?? [])].sort((a, b) =>
    a.created_at.localeCompare(b.created_at) || a.public_id.localeCompare(b.public_id));

  return (
    <li
      id={`observation-${item.public_id}`}
      data-testid={`observation-${item.public_id}`}
      data-status={item.status}
      className="min-w-0 rounded-2xl border border-border bg-card p-4"
    >
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <StatusBadge variant={STATUS_VARIANT[item.status]}>{t.status[item.status]}</StatusBadge>
        <span className="min-w-0 font-medium [overflow-wrap:anywhere]">{item.author_email}</span>
        <span className="text-xs text-muted-foreground">
          {interpolate(t.onVersion, { version: item.created_on })}
          {item.resolved_in ? ` · ${interpolate(t.resolvedIn, { version: item.resolved_in })}` : ''}
        </span>
      </div>
      {item.section_heading ? (
        <button
          data-testid={`observation-anchor-${item.public_id}`}
          className="mt-1 text-left text-xs text-primary underline-offset-2 hover:underline disabled:opacity-50 [overflow-wrap:anywhere]"
          disabled={!anchor || anchorContent?.isLoading}
          onClick={() => void selectAnchor()}
          type="button"
        >
          {item.section_heading}{anchor ? ` — ${t.anchor[anchor.method]}` : ''}
        </button>
      ) : anchor ? (
        <button
          data-testid={`observation-anchor-${item.public_id}`}
          className="mt-1 text-xs text-primary disabled:opacity-50"
          disabled={anchorContent?.isLoading}
          onClick={() => void selectAnchor()}
          type="button"
        >
          {common.page} {anchor.page} — {t.anchor[anchor.method]}
        </button>
      ) : null}
      {anchorRequested && anchorContent && !anchorContent.eof ? (
        <button
          data-testid={`observation-anchor-more-${item.public_id}`}
          className="mt-1 block text-xs text-primary disabled:opacity-50"
          disabled={anchorContent.isLoading}
          onClick={() => void selectAnchor()}
          type="button"
        >
          {anchorContent.isLoading ? common.loading : anchorContent.error ? common.retry : t.loadMoreAnchor}
        </button>
      ) : null}
      {anchorContent?.error || anchorError ? (
        <p role="alert" className="mt-1 text-xs text-destructive">{anchorContent?.error ?? anchorError}</p>
      ) : null}
      <div className="mt-1">
        <ProgressiveObservationText summary={item} testId={`observation-text-${item.public_id}`} />
      </div>

      {item.reply_count > 0 ? (
        <div className="mt-2">
          <button
            data-testid={`observation-replies-${item.public_id}`}
            className={ACTION_CLASS}
            aria-expanded={showReplies}
            onClick={() => {
              setShowReplies((value) => !value);
              if (!showReplies && !replies?.isLoaded) void loadReplies(item.public_id);
            }}
            type="button"
          >
            {showReplies ? t.hideReplies : interpolate(t.showReplies, { count: item.reply_count })}
          </button>
          {showReplies ? (
            <div className="mt-2 flex flex-col gap-2">
              {replies?.isLoading && !replies.isLoaded ? <p role="status" className="text-xs">{common.loading}</p> : null}
              {replies?.error ? <p role="alert" className="text-xs text-destructive">{replies.error}</p> : null}
              {replies?.nextCursor || (replies && !replies.isLoaded && !replies.isLoading) ? (
                <button
                  data-testid={`observation-replies-more-${item.public_id}`}
                  className={`${ACTION_CLASS} self-start`}
                  disabled={replies?.isLoading}
                  onClick={() => void loadReplies(item.public_id)}
                  type="button"
                >
                  {replies?.isLoading ? common.loading : replies?.error ? common.retry : t.loadOlderReplies}
                </button>
              ) : null}
              {visibleReplies.map((replyRow) => (
                <div key={replyRow.public_id} data-testid={`observation-reply-${replyRow.public_id}`} className="min-w-0 rounded-xl bg-muted/40 px-3 py-2 text-sm">
                  <span className="font-medium [overflow-wrap:anywhere]">{replyRow.author_email}</span>
                  <ProgressiveObservationText summary={replyRow} testId={`observation-reply-text-${replyRow.public_id}`} />
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="mt-2 flex flex-wrap items-center gap-2">
        {canReply && item.status !== 'resolved' ? (
          <>
            <input
              data-testid={`reply-input-${item.public_id}`}
              className="min-w-0 flex-1 rounded-lg border border-border bg-background px-3 py-1.5 text-sm"
              placeholder={t.replyPlaceholder}
              aria-label={t.replyPlaceholder}
              value={replyDraft}
              disabled={busy}
              onChange={(event) => setReplyDraft(event.target.value)}
            />
            <button
              data-testid={`reply-send-${item.public_id}`}
              className={ACTION_CLASS}
              disabled={busy}
              onClick={() => void act(reply(versionId, item.public_id, replyDraft)).then((ok) => {
                if (ok) { setReplyDraft(''); setShowReplies(true); }
              })}
              type="button"
            >
              {t.reply}
            </button>
          </>
        ) : null}
        {item.status === 'answered' && (item.author_email === currentUserEmail || canResolveAny) ? (
          <button
            data-testid={`resolve-${item.public_id}`}
            className="rounded-full bg-primary px-3 py-1.5 text-xs text-primary-foreground disabled:opacity-50"
            disabled={busy}
            onClick={() => void act(setStatus(versionId, item.public_id, 'resolved'))}
            type="button"
          >
            {t.resolve}
          </button>
        ) : null}
        {item.status === 'resolved' && item.author_email === currentUserEmail ? (
          <button
            data-testid={`reopen-${item.public_id}`}
            className={ACTION_CLASS}
            disabled={busy}
            onClick={() => void act(setStatus(versionId, item.public_id, 'open'))}
            type="button"
          >
            {t.reopen}
          </button>
        ) : null}
      </div>

      <div className="mt-2">
        <button
          data-testid={`observation-history-${item.public_id}`}
          className="text-xs text-muted-foreground underline-offset-2 hover:underline"
          aria-expanded={showHistory}
          onClick={() => {
            setShowHistory((value) => !value);
            if (!showHistory && !anchors?.isLoaded) void loadAnchors(item.public_id);
          }}
          type="button"
        >
          {showHistory ? t.hideHistory : t.showHistory}
        </button>
        {showHistory ? (
          <div className="mt-2 text-xs">
            {anchors?.isLoading && !anchors.isLoaded ? <p role="status">{common.loading}</p> : null}
            {anchors?.error ? <p role="alert" className="text-destructive">{anchors.error}</p> : null}
            <ol data-testid={`observation-history-list-${item.public_id}`} className="flex flex-col gap-1">
              {(anchors?.items ?? []).map((historic) => (
                <li key={historic.version_number} className="rounded-lg bg-muted/40 px-2 py-1 [overflow-wrap:anywhere]">
                  v{historic.version_number} · {common.page} {historic.page} · {t.anchor[historic.method]}
                  {historic.text_snippet ? <p>{historic.text_snippet}</p> : null}
                  {historic.version_is_trashed ? <p>{t.historyVersionTrashed}</p> : null}
                  {pathname && !historic.version_is_trashed ? (
                    <Link
                      data-testid={`observation-history-version-${item.public_id}-${historic.version_number}`}
                      className="text-primary underline-offset-2 hover:underline"
                      href={`${pathname.replace(/\/versions\/[^/]+\/?$/, `/versions/${historic.version_public_id}`)}?observation=${item.public_id}#observation-${item.public_id}`}
                    >
                      {interpolate(t.viewHistoryVersion, { version: historic.version_number })}
                    </Link>
                  ) : null}
                </li>
              ))}
            </ol>
            {anchors?.nextCursor || (anchors?.error && !anchors.isLoaded) ? (
              <button
                data-testid={`observation-history-more-${item.public_id}`}
                className={`${ACTION_CLASS} mt-2`}
                disabled={anchors?.isLoading}
                onClick={() => void loadAnchors(item.public_id)}
                type="button"
              >
                {anchors?.isLoading ? common.loading : anchors?.error ? common.retry : t.loadMoreHistory}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
    </li>
  );
}
