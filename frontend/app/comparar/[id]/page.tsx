'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useEffect } from 'react';

import { PublicCompareCta } from '@/components/public-compare/PublicCompareCta';
import { PublicCompareResult } from '@/components/public-compare/PublicCompareResult';
import { Skeleton } from '@/components/ui/Skeleton';
import { ROUTES } from '@/lib/constants';
import { interpolate, useDict } from '@/lib/i18n/dictionaries';
import {
  PUBLIC_COMPARE_MAX_MB,
  PUBLIC_COMPARE_MAX_PAGES,
  PUBLIC_COMPARE_TTL_HOURS,
  usePublicCompareStore,
} from '@/lib/stores/publicCompareStore';

export default function CompararResultPage() {
  const params = useParams<{ id: string }>();
  const t = useDict('publicCompare');
  const phase = usePublicCompareStore((s) => s.phase);
  const detail = usePublicCompareStore((s) => s.detail);
  const errorKey = usePublicCompareStore((s) => s.errorKey);
  const load = usePublicCompareStore((s) => s.load);

  useEffect(() => {
    const controller = new AbortController();
    if (params?.id) void load(params.id, controller.signal);
    return () => controller.abort();
  }, [params?.id, load]);

  const errorMessage =
    errorKey &&
    interpolate(
      {
        missingFiles: t.errorMissingFiles,
        notPdf: t.errorNotPdf,
        tooBig: t.errorTooBig,
        tooManyPages: t.errorTooManyPages,
        scannedNeedsOcr: t.errorScannedNeedsOcr,
        encrypted: t.errorEncrypted,
        invalid: t.errorInvalid,
        rateLimited: t.errorRateLimited,
        genericFailed: t.errorGenericFailed,
        expired: t.errorExpired,
      }[errorKey],
      { mb: PUBLIC_COMPARE_MAX_MB, pages: PUBLIC_COMPARE_MAX_PAGES }
    );

  return (
    <>
      <main className="max-w-5xl mx-auto px-6 py-14">
        {phase === 'done' && detail ? (
          <>
            <PublicCompareResult detail={detail} />
            <p className="mt-8 text-xs text-muted-foreground">
              {interpolate(t.share, { hours: PUBLIC_COMPARE_TTL_HOURS })} ·{' '}
              {interpolate(t.privacyNote, { hours: PUBLIC_COMPARE_TTL_HOURS })}
            </p>
            <Link
              className="mt-4 inline-block rounded-full border border-border px-4 py-2 text-sm hover:bg-accent hover:text-accent-foreground"
              href={ROUTES.COMPARAR}
            >
              {t.newComparison}
            </Link>
          </>
        ) : errorMessage ? (
          <div className="max-w-xl">
            <p
              role="alert"
              data-testid="public-compare-error"
              className="rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive"
            >
              {errorMessage}
            </p>
            <Link
              className="mt-4 inline-block rounded-full bg-primary text-primary-foreground px-5 py-2.5 text-sm hover:bg-primary/90"
              href={ROUTES.COMPARAR}
            >
              {t.newComparison}
            </Link>
          </div>
        ) : (
          <div className="flex flex-col gap-4" role="status" aria-label={t.processing}>
            <p className="text-sm text-muted-foreground">{t.processing}</p>
            <p className="text-xs text-muted-foreground">{t.processingHint}</p>
            <Skeleton className="h-24 w-full rounded-2xl" />
            <Skeleton className="h-40 w-full rounded-2xl" />
          </div>
        )}
      </main>
      <PublicCompareCta />
    </>
  );
}
