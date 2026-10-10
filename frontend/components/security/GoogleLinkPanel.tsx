'use client';

import { GoogleLogin } from '@react-oauth/google';
import { useRouter } from 'next/navigation';
import { FormEvent, useEffect, useRef, useState } from 'react';

import { useDict } from '@/lib/i18n/dictionaries';
import { apiErrorMessage } from '@/lib/services/errors';
import { clearGoogleLinkTicket, getGoogleLinkTicket } from '@/lib/services/google-link-ticket';
import { api } from '@/lib/services/http';
import { setTokens } from '@/lib/services/tokens';
import { useAuthStore } from '@/lib/stores/authStore';

export function GoogleLinkPanel({ linked, hasUsablePassword, totpEnabled, onLinked }: {
  linked: boolean;
  hasUsablePassword: boolean;
  totpEnabled: boolean;
  onLinked: () => Promise<void>;
}) {
  const t = useDict('googleLink');
  const router = useRouter();
  const [ticket, setTicket] = useState<string | null>(null);
  const [credential, setCredential] = useState('');
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [code, setCode] = useState('');
  const [pending, setPending] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const submitting = useRef(false);

  useEffect(() => { setTicket(getGoogleLinkTicket()); }, []);

  const recover = () => {
    useAuthStore.getState().signOut();
    router.push('/forgot-password');
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (submitting.current || uncertain || success) return;
    setError('');
    const proof = getGoogleLinkTicket();
    if (!proof) { setTicket(null); setError(t.expired); return; }
    if (newPassword !== confirmPassword) { setError(t.mismatch); return; }
    if (newPassword === currentPassword || newPassword.length < 8) { setError(t.distinct); return; }
    if (!credential || !currentPassword || (totpEnabled && !code.trim())) return;
    submitting.current = true;
    setPending(true);
    try {
      const { data } = await api.post('me/google/link/', {
        credential, google_link_ticket: proof, current_password: currentPassword,
        new_password: newPassword, ...(totpEnabled ? { code } : {}),
      });
      if (!data.access || !data.refresh || !data.user) throw new Error('Invalid token response');
      setTokens({ access: data.access, refresh: data.refresh });
      localStorage.setItem('user_data', JSON.stringify(data.user));
      useAuthStore.setState({ user: data.user });
      useAuthStore.getState().syncFromCookies();
      clearGoogleLinkTicket();
      setTicket(null);
      setCredential('');
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
      setCode('');
      setSuccess(true);
      await onLinked();
    } catch (err) {
      const status = (err as { response?: { status?: number } }).response?.status;
      if (!status || status >= 500 || status === 401) {
        setUncertain(true);
        setError(t.uncertain);
      } else {
        setError(apiErrorMessage(err, t.error));
      }
    } finally {
      submitting.current = false;
      setPending(false);
    }
  };

  return (
    <div data-testid="google-link-panel" className="mt-4 rounded-2xl border border-border bg-card p-4">
      <h3 className="font-medium">{t.title}</h3>
      {success && <p role="status" className="mt-2 text-sm">{t.success}</p>}
      {error && <p role="alert" className="mt-2 text-sm text-destructive">{error}</p>}
      {success ? null : uncertain ? (
        <button type="button" className="mt-3 underline" onClick={() => {
          useAuthStore.getState().signOut();
          router.push('/sign-in?next=/settings');
        }}>{t.signIn}</button>
      ) : linked ? (
        <p className="mt-2 text-sm text-muted-foreground">{t.linked}</p>
      ) : !hasUsablePassword || !ticket ? (
        <>
          <p className="mt-2 text-sm text-muted-foreground">{t.recoveryHint}</p>
          <button data-testid="google-link-recover" type="button" className="mt-3 underline" onClick={recover}>{t.recovery}</button>
        </>
      ) : (
        <form data-testid="google-link-form" onSubmit={submit} className="mt-3 space-y-3">
          <p className="text-sm text-muted-foreground">{t.hint}</p>
          <label className="block text-sm">{t.currentPassword}
            <input data-testid="google-link-current" className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2" type="password" autoComplete="current-password" required disabled={pending} value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} />
          </label>
          <label className="block text-sm">{t.newPassword}
            <input data-testid="google-link-new" className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2" type="password" autoComplete="new-password" minLength={8} required disabled={pending} value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
          </label>
          <label className="block text-sm">{t.confirmPassword}
            <input data-testid="google-link-confirm" className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2" type="password" autoComplete="new-password" required disabled={pending} value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} />
          </label>
          {totpEnabled && <label className="block text-sm">{t.code}
            <input data-testid="google-link-code" className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2" required autoComplete="one-time-code" disabled={pending} value={code} onChange={(e) => setCode(e.target.value)} />
          </label>}
          {!pending && process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID && <div className="overflow-hidden">
            <p className="mb-2 text-sm">{t.chooseGoogle}</p>
            <GoogleLogin onSuccess={({ credential: token }) => {
              setCredential(token || '');
            }} onError={() => { setCredential(''); setError(t.error); }} />
          </div>}
          {credential && <p role="status" className="text-sm">{t.googleReady}</p>}
          <button type="button" className="block text-sm underline" disabled={pending} onClick={recover}>{t.recovery}</button>
          <button data-testid="google-link-submit" type="submit" className="rounded-full bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-50" disabled={pending || !credential || !currentPassword || !newPassword || !confirmPassword || (totpEnabled && !code.trim())}>{t.submit}</button>
        </form>
      )}
    </div>
  );
}
