import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Lock, Mail, ShieldCheck, User as UserIcon } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { Button } from '../components/ui';

export const LoginPage: React.FC = () => {
  const { login, register } = useAuth();
  const navigate = useNavigate();

  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [fullName, setFullName] = useState('');
  const [password, setPassword] = useState('');
  const [mfaCode, setMfaCode] = useState('');
  const [needMfa, setNeedMfa] = useState(false);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      if (mode === 'login') {
        await login(email, password, mfaCode || undefined);
      } else {
        await register(email, fullName, password);
      }
      navigate('/');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'خطا در احراز هویت';
      setError(msg);
      if (msg.includes('MFA') || msg.includes('دومرحله')) {
        setNeedMfa(true);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const fillDevAdmin = () => {
    setMode('login');
    setEmail('admin@nexvora.local');
    setPassword('NexvoraAdmin!2026');
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-nx-bg p-4">
      <div className="w-full max-w-md nx-card-gold rounded-3xl p-6 sm:p-8">
        <div className="flex items-center gap-3">
          <img src="/icons/nexvora-icon.svg" alt="NEXVORA" className="h-12 w-12 rounded-2xl" />
          <div>
            <h1 className="text-xl font-extrabold text-nx-text">NEXVORA PWA</h1>
            <p className="text-xs text-nx-gold">هوش معاملاتی فارکس | Trading Hub 3.0</p>
          </div>
        </div>

        <div className="mt-6 grid grid-cols-2 gap-1 rounded-xl bg-nx-bg/70 p-1">
          <button
            type="button"
            onClick={() => {
              setMode('login');
              setError('');
            }}
            className={`rounded-lg py-2 text-xs font-bold transition ${
              mode === 'login' ? 'bg-nx-elevated text-nx-gold' : 'text-nx-muted'
            }`}
          >
            ورود به حساب
          </button>
          <button
            type="button"
            onClick={() => {
              setMode('register');
              setError('');
            }}
            className={`rounded-lg py-2 text-xs font-bold transition ${
              mode === 'register' ? 'bg-nx-elevated text-nx-gold' : 'text-nx-muted'
            }`}
          >
            ثبت‌نام کاربر جدید
          </button>
        </div>

        <form onSubmit={handleSubmit} className="mt-5 space-y-4">
          {mode === 'register' && (
            <div>
              <label className="mb-1.5 block text-xs text-nx-muted">نام و نام خانوادگی</label>
              <div className="relative">
                <UserIcon className="pointer-events-none absolute right-3 top-2.5 h-4 w-4 text-nx-muted" />
                <input
                  type="text"
                  required
                  minLength={2}
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder="مثلاً علی رضایی"
                  className="w-full rounded-xl border border-nx-border bg-nx-bg/70 pr-10 pl-3 py-2 text-sm text-nx-text focus:border-nx-gold focus:outline-none"
                />
              </div>
            </div>
          )}

          <div>
            <label className="mb-1.5 block text-xs text-nx-muted">ایمیل</label>
            <div className="relative">
              <Mail className="pointer-events-none absolute right-3 top-2.5 h-4 w-4 text-nx-muted" />
              <input
                type="email"
                dir="ltr"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@example.com"
                className="w-full rounded-xl border border-nx-border bg-nx-bg/70 pr-10 pl-3 py-2 text-sm text-nx-text text-left focus:border-nx-gold focus:outline-none"
              />
            </div>
          </div>

          <div>
            <label className="mb-1.5 block text-xs text-nx-muted">
              رمز عبور {mode === 'register' && '(حداقل ۱۰ کاراکتر شامل حروف و عدد)'}
            </label>
            <div className="relative">
              <Lock className="pointer-events-none absolute right-3 top-2.5 h-4 w-4 text-nx-muted" />
              <input
                type="password"
                dir="ltr"
                required
                minLength={mode === 'register' ? 10 : 1}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••••"
                className="w-full rounded-xl border border-nx-border bg-nx-bg/70 pr-10 pl-3 py-2 text-sm text-nx-text text-left focus:border-nx-gold focus:outline-none"
              />
            </div>
          </div>

          {needMfa && mode === 'login' && (
            <div>
              <label className="mb-1.5 block text-xs text-nx-gold">کد احراز هویت دومرحله‌ای (MFA)</label>
              <input
                type="text"
                dir="ltr"
                value={mfaCode}
                onChange={(e) => setMfaCode(e.target.value)}
                placeholder="123456"
                className="w-full rounded-xl border border-nx-gold/50 bg-nx-bg/70 px-3 py-2 text-center font-mono text-sm tracking-widest text-nx-text focus:outline-none"
              />
            </div>
          )}

          {error && (
            <div className="rounded-xl border border-nx-loss/40 bg-nx-loss/10 px-3 py-2 text-xs text-nx-loss">
              {error}
            </div>
          )}

          <Button type="submit" variant="gold" className="w-full py-2.5" disabled={submitting}>
            {submitting ? 'در حال بررسی...' : mode === 'login' ? 'ورود امن به پنل' : 'ایجاد حساب کاربری'}
          </Button>
        </form>

        <div className="mt-5 rounded-xl border border-nx-border/70 bg-nx-bg/50 p-3 text-xs text-nx-muted">
          <div className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-1.5 text-nx-text font-medium">
              <ShieldCheck className="h-4 w-4 text-nx-profit" />
              حساب ادمین اولیه (محیط توسعه):
            </span>
            <button
              type="button"
              onClick={fillDevAdmin}
              className="text-nx-gold hover:underline font-medium"
            >
              پر کردن خودکار
            </button>
          </div>
          <div className="mt-1.5 font-mono text-[11px] text-nx-muted" dir="ltr">
            admin@nexvora.local / NexvoraAdmin!2026
          </div>
        </div>
      </div>
    </div>
  );
};
