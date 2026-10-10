'use client';

/** A3 — 2FA lifecycle + active sessions (mounted in /settings). */

import { useCallback, useEffect, useState } from 'react';

import { GoogleLinkPanel } from './GoogleLinkPanel';

import { StatusBadge } from '@/components/ui/StatusBadge';
import { useToast } from '@/components/ui/toast';
import { useDict } from '@/lib/i18n/dictionaries';
import { api } from '@/lib/services/http';
import { getRefreshToken } from '@/lib/services/tokens';

interface SecurityState {
  totp_enabled: boolean;
  backup_codes_left: number;
  sso: string;
  google_linked: boolean;
  has_usable_password: boolean;
}

interface SessionRow {
  id: number;
  jti: string;
  created_at: string;
  expires_at: string;
}

function formatDate(iso: string) {
  return new Intl.DateTimeFormat('es', { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(iso)
  );
}

export function SecuritySection() {
  const t = useDict('security');
  const common = useDict('common');
  const { toast } = useToast();
  const [state, setState] = useState<SecurityState | null>(null);
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [setup, setSetup] = useState<{ qr: string; secret: string } | null>(null);
  const [code, setCode] = useState('');
  const [backupCodes, setBackupCodes] = useState<string[] | null>(null);
  const [disableCode, setDisableCode] = useState('');

  const load = useCallback(async () => {
    try {
      const [{ data: security }, { data: sessionData }] = await Promise.all([
        api.get<SecurityState>('me/security/'),
        api.get('me/sessions/'),
      ]);
      setState(security);
      setSessions(sessionData.results);
    } catch {
      // settings page shows its own error surface
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (!state) return null;

  const act = async (fn: () => Promise<unknown>, okMessage = common.saved) => {
    try {
      await fn();
      toast(okMessage, 'success');
      await load();
      return true;
    } catch (err) {
      toast(
        (err as { response?: { data?: { error?: string } } })?.response?.data?.error ??
          common.error,
        'error'
      );
      return false;
    }
  };

  return (
    <section data-testid="security-section" className="mt-10">
      <h2 className="text-lg font-semibold">{t.title}</h2>

      <GoogleLinkPanel linked={state.google_linked} hasUsablePassword={state.has_usable_password}
        totpEnabled={state.totp_enabled} onLinked={load} />

      {/* ── 2FA ── */}
      <div className="mt-4 rounded-2xl border border-border bg-card p-4">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="font-medium">{t.twofa}</h3>
          <StatusBadge variant={state.totp_enabled ? 'approved' : 'neutral'}>
            {state.totp_enabled ? t.enabled : t.disabled}
          </StatusBadge>
          {state.totp_enabled ? (
            <span className="text-xs text-muted-foreground">
              {state.backup_codes_left} {t.codesLeft}
            </span>
          ) : null}
        </div>

        {backupCodes ? (
          <div data-testid="backup-codes" className="mt-3 rounded-xl bg-muted/40 p-3">
            <p className="font-medium">{t.backupTitle}</p>
            <p className="text-xs text-muted-foreground">{t.backupBody}</p>
            <ul className="mt-2 grid grid-cols-2 gap-1 font-mono text-sm sm:grid-cols-4">
              {backupCodes.map((backupCode) => (
                <li key={backupCode}>{backupCode}</li>
              ))}
            </ul>
            <button
              data-testid="backup-saved"
              className="mt-3 rounded-full bg-primary px-4 py-2 text-sm text-primary-foreground"
              onClick={() => setBackupCodes(null)}
              type="button"
            >
              {t.backupDone}
            </button>
          </div>
        ) : state.totp_enabled ? (
          <div className="mt-3 flex flex-wrap items-end gap-2">
            <label className="block text-sm">
              <span className="text-muted-foreground">{t.disableHint}</span>
              <input
                data-testid="disable-code"
                className="mt-1 w-40 rounded-lg border border-border bg-background px-3 py-2"
                value={disableCode}
                onChange={(event) => setDisableCode(event.target.value)}
              />
            </label>
            <button
              data-testid="disable-2fa"
              className="rounded-full border border-destructive/50 px-4 py-2 text-sm text-destructive hover:bg-destructive/10"
              onClick={() =>
                void act(() => api.post('me/2fa/disable/', { code: disableCode })).then(() =>
                  setDisableCode('')
                )
              }
              type="button"
            >
              {t.disable}
            </button>
          </div>
        ) : setup ? (
          <div className="mt-3">
            <p className="text-sm text-muted-foreground">{t.scan}</p>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img data-testid="twofa-qr" src={setup.qr} alt="QR TOTP" className="mt-2 h-40 w-40" />
            <p data-testid="twofa-secret" className="mt-1 font-mono text-xs text-muted-foreground">
              {setup.secret}
            </p>
            <div className="mt-2 flex items-center gap-2">
              <input
                data-testid="enable-code"
                className="w-36 rounded-lg border border-border bg-background px-3 py-2 text-center tracking-widest"
                placeholder={t.code}
                value={code}
                onChange={(event) => setCode(event.target.value)}
              />
              <button
                data-testid="enable-2fa"
                className="rounded-full bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-50"
                disabled={!code.trim()}
                onClick={() =>
                  void api
                    .post('me/2fa/enable/', { code })
                    .then(({ data }) => {
                      setBackupCodes(data.backup_codes);
                      setSetup(null);
                      setCode('');
                      void load();
                    })
                    .catch((err) =>
                      toast(err.response?.data?.error ?? common.error, 'error')
                    )
                }
                type="button"
              >
                {t.confirm}
              </button>
            </div>
          </div>
        ) : (
          <button
            data-testid="start-2fa"
            className="mt-3 rounded-full bg-primary px-4 py-2 text-sm text-primary-foreground"
            onClick={() =>
              void api
                .post('me/2fa/setup/')
                .then(({ data }) => setSetup({ qr: data.qr, secret: data.secret }))
                .catch((err) => toast(err.response?.data?.error ?? common.error, 'error'))
            }
            type="button"
          >
            {t.start}
          </button>
        )}
      </div>

      {/* ── Sesiones activas ── */}
      <div className="mt-4 rounded-2xl border border-border bg-card p-4">
        <div className="flex items-center justify-between gap-2">
          <h3 className="font-medium">{t.sessions}</h3>
          {sessions.length > 1 ? (
            <button
              data-testid="revoke-others"
              className="rounded-full border border-border px-3 py-1.5 text-xs hover:bg-accent"
              onClick={() =>
                void act(() =>
                  api.post('me/sessions/revoke_others/', { refresh: getRefreshToken() })
                )
              }
              type="button"
            >
              {t.revokeOthers}
            </button>
          ) : null}
        </div>
        <ul data-testid="sessions-list" className="mt-2 flex flex-col gap-1.5">
          {sessions.map((session) => (
            <li
              key={session.id}
              className="flex items-center justify-between gap-2 rounded-xl border border-border px-3 py-2 text-sm"
            >
              <span className="font-mono text-xs">{session.jti}…</span>
              <span className="text-xs text-muted-foreground">
                {t.thisDevice} {formatDate(session.created_at)} · {t.expires}{' '}
                {formatDate(session.expires_at)}
              </span>
              <button
                className="text-xs text-destructive underline-offset-2 hover:underline"
                onClick={() => void act(() => api.post(`me/sessions/${session.id}/revoke/`))}
                type="button"
              >
                {t.revoke}
              </button>
            </li>
          ))}
        </ul>
      </div>

      <p className="mt-3 text-xs text-muted-foreground">
        {t.sso}: {t.ssoPending}
      </p>
    </section>
  );
}
