'use client';

import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { FormEvent, useState, useEffect, useRef } from 'react';
import { GoogleLogin, CredentialResponse } from '@react-oauth/google';
import { jwtDecode } from 'jwt-decode';
import ReCAPTCHA from 'react-google-recaptcha';

import { useAuthStore } from '@/lib/stores/authStore';
import { useDict } from '@/lib/i18n/dictionaries';
import { api } from '@/lib/services/http';
import { apiErrorMessage } from '@/lib/services/errors';

type GoogleUser = {
  email: string;
  given_name?: string;
  family_name?: string;
  picture?: string;
};

export default function SignInPage() {
  const router = useRouter();
  const { signIn, signIn2fa, googleLogin } = useAuthStore();
  const t = useDict('auth');
  const googleLink = useDict('googleLink');
  const [linkRequired, setLinkRequired] = useState(false);
  const [challenge, setChallenge] = useState<string | null>(null);
  const [totpCode, setTotpCode] = useState('');

  const hasGoogleClientId = Boolean(process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID);

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [captchaToken, setCaptchaToken] = useState<string | null>(null);
  const [siteKey, setSiteKey] = useState<string>('');
  const recaptchaRef = useRef<ReCAPTCHA>(null);

  useEffect(() => {
    api.get('google-captcha/site-key/')
      .then((res) => setSiteKey(res.data.site_key || ''))
      .catch(() => {});
  }, []);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');

    if (siteKey && !captchaToken) {
      setError(t.errorCaptcha);
      return;
    }

    setLoading(true);

    try {
      const result = await signIn({ email, password, captcha_token: captchaToken ?? undefined });
      if (result.requires2fa) {
        setChallenge(result.challenge);
        return;
      }
      const next = new URLSearchParams(window.location.search).get('next');
      router.replace(next && next.startsWith('/') ? next : '/projects');
    } catch (err) {
      setError(apiErrorMessage(err, t.errorInvalidCredentials));
      recaptchaRef.current?.reset();
      setCaptchaToken(null);
    } finally {
      setLoading(false);
    }
  };

  const handleGoogleSuccess = async (credentialResponse: CredentialResponse) => {
    try {
      setLoading(true);
      setError('');
      setLinkRequired(false);

      if (!credentialResponse.credential) {
        setError(t.errorGoogle);
        return;
      }

      let decoded: GoogleUser | null = null;
      try {
        decoded = jwtDecode<GoogleUser>(credentialResponse.credential);
      } catch {
        decoded = null;
      }

      const result = await googleLogin({
        credential: credentialResponse.credential,
        email: decoded?.email,
        given_name: decoded?.given_name,
        family_name: decoded?.family_name,
        picture: decoded?.picture,
      });
      if (result.requires2fa) {
        setChallenge(result.challenge);
        return;
      }
      
      router.replace('/projects');
    } catch (err) {
      const data = (err as { response?: { status?: number; data?: { code?: string } } }).response;
      if (data?.status === 409 && data.data?.code === 'google_link_required') {
        setLinkRequired(true);
        setError('');
      } else {
        setError(apiErrorMessage(err, t.errorGoogle));
      }
    } finally {
      setLoading(false);
    }
  };

  const handleGoogleError = () => {
    setError(t.errorGoogle);
  };

  return (
    <main className="min-h-[calc(100vh-72px)] flex items-center justify-center px-6 py-12">
      <div className="w-full max-w-md bg-card border border-border rounded-2xl p-6 shadow-sm">
        <h1 className="text-2xl font-semibold tracking-tight">{t.signInTitle}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{t.signInSubtitle}</p>

        {challenge ? (
          <form
            data-testid="twofa-step"
            className="mt-6 space-y-4"
            onSubmit={async (e) => {
              e.preventDefault();
              setError('');
              setLoading(true);
              try {
                await signIn2fa({ challenge, code: totpCode });
                const next = new URLSearchParams(window.location.search).get('next');
                router.replace(next && next.startsWith('/') ? next : '/projects');
              } catch (err) {
                setError(apiErrorMessage(err, t.twofaInvalid));
              } finally {
                setLoading(false);
              }
            }}
          >
            <p className="text-sm font-medium">{t.twofaTitle}</p>
            <p className="text-sm text-muted-foreground">{t.twofaHint}</p>
            <input
              data-testid="twofa-code"
              className="border border-border rounded-xl px-3 py-2 w-full bg-card text-center tracking-widest"
              placeholder="000000"
              value={totpCode}
              onChange={(e) => setTotpCode(e.target.value)}
              autoFocus
            />
            {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
            <button
              data-testid="twofa-verify"
              className="w-full bg-primary text-primary-foreground rounded-full px-4 py-2 disabled:opacity-60"
              disabled={loading || !totpCode.trim()}
              type="submit"
            >
              {t.twofaVerify}
            </button>
          </form>
        ) : (
        <form className="mt-6 space-y-4" onSubmit={onSubmit}>
          <div>
            <input 
              className="border border-border rounded-xl px-3 py-2 w-full bg-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              placeholder="Email" 
              type="email"
              value={email} 
              onChange={(e) => setEmail(e.target.value)} 
              autoComplete="email"
              required
            />
          </div>
          
          <div>
            <input 
              className="border border-border rounded-xl px-3 py-2 w-full bg-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              placeholder="Password" 
              value={password} 
              onChange={(e) => setPassword(e.target.value)} 
              type="password" 
              autoComplete="current-password"
              required
            />
          </div>

          {siteKey && (
            <div className="flex justify-center">
              <ReCAPTCHA
                ref={recaptchaRef}
                sitekey={siteKey}
                onChange={(token) => setCaptchaToken(token)}
                onExpired={() => setCaptchaToken(null)}
              />
            </div>
          )}

          <button
            className="bg-primary text-primary-foreground rounded-full px-5 py-3 w-full disabled:opacity-50 hover:bg-primary/90"
            type="submit"
            disabled={loading}
          >
            {loading ? t.signingIn : t.signIn}
          </button>

          {error ? <p className="text-destructive text-sm">{error}</p> : null}
        </form>
        )}

        <div className="mt-4 text-center">
          <Link href="/forgot-password" className="text-sm text-foreground hover:underline">
            {t.forgot}
          </Link>
        </div>

        {linkRequired && <div data-testid="google-link-required" role="status" className="mt-4 space-y-2 text-sm">
          <p>{googleLink.legacy}</p>
          <Link href="/forgot-password" className="underline" onClick={() => useAuthStore.getState().signOut()}>{googleLink.recovery}</Link>
        </div>}

        <div className="mt-6">
          <div className="relative">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-border"></div>
            </div>
            <div className="relative flex justify-center text-sm">
              <span className="px-2 bg-card text-muted-foreground">{t.orContinue}</span>
            </div>
          </div>

          {hasGoogleClientId ? (
            <div className="mt-6 flex justify-center">
              <GoogleLogin
                onSuccess={handleGoogleSuccess}
                onError={handleGoogleError}
                size="large"
                text="signin_with"
                shape="rectangular"
              />
            </div>
          ) : (
            <p className="mt-6 text-sm text-destructive text-center">Missing NEXT_PUBLIC_GOOGLE_CLIENT_ID</p>
          )}
        </div>

        <div className="mt-6 text-center text-sm">
          <span className="text-muted-foreground">{t.noAccount} </span>
          <Link href="/sign-up" className="text-foreground hover:underline">
            {t.signUpLink}
          </Link>
        </div>
      </div>
    </main>
  );
}
