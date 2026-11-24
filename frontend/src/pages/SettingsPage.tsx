import React, { useCallback, useEffect, useState } from 'react';
import { KeyRound, Laptop, Settings, ShieldCheck } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { apiFetch } from '../lib/api';
import type { SessionInfo } from '../types';
import { formatDateTimeFa } from '../lib/format';
import { Badge, Button, LtrValue } from '../components/ui';

export const SettingsPage: React.FC = () => {
  const { user, refreshMe } = useAuth();
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [pwdMsg, setPwdMsg] = useState('');

  // MFA Setup State
  const [mfaSecret, setMfaSecret] = useState('');
  const [mfaUri, setMfaUri] = useState('');
  const [mfaCode, setMfaCode] = useState('');
  const [mfaMsg, setMfaMsg] = useState('');

  const loadSessions = useCallback(async () => {
    try {
      const s = await apiFetch<SessionInfo[]>('/api/v1/auth/sessions');
      setSessions(s);
    } catch {
      /* noop */
    }
  }, []);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  const handlePasswordChange = async (e: React.FormEvent) => {
    e.preventDefault();
    setPwdMsg('');
    try {
      const res = await apiFetch<{ message: string }>('/api/v1/auth/change-password', {
        method: 'POST',
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      setPwdMsg(res.message);
      setCurrentPassword('');
      setNewPassword('');
      loadSessions();
    } catch (err) {
      setPwdMsg(err instanceof Error ? err.message : 'خطا در تغییر رمز عبور');
    }
  };

  const startMfaSetup = async () => {
    setMfaMsg('');
    try {
      const res = await apiFetch<{ secret: string; otpauth_uri: string }>('/api/v1/auth/mfa/setup', {
        method: 'POST',
      });
      setMfaSecret(res.secret);
      setMfaUri(res.otpauth_uri);
    } catch (err) {
      setMfaMsg(err instanceof Error ? err.message : 'خطا');
    }
  };

  const verifyMfa = async () => {
    setMfaMsg('');
    try {
      await apiFetch<{ status: string; mfa_enabled: boolean }>(
        `/api/v1/auth/mfa/enable?code=${encodeURIComponent(mfaCode)}`,
        { method: 'POST' },
      );
      setMfaMsg('احراز هویت دومرحله‌ای با موفقیت فعال شد.');
      setMfaSecret('');
      setMfaCode('');
      await refreshMe();
    } catch (err) {
      setMfaMsg(err instanceof Error ? err.message : 'کد تایید نامعتبر است');
    }
  };

  const revokeSession = async (id: number) => {
    await apiFetch(`/api/v1/auth/sessions/${id}`, { method: 'DELETE' });
    loadSessions();
  };

  return (
    <div className="space-y-5">
      <div>
        <h1 className="flex items-center gap-2 text-lg font-extrabold text-nx-text">
          <Settings className="h-5 w-5 text-nx-gold" />
          تنظیمات حساب، امنیت نشست‌ها و MFA
        </h1>
        <p className="text-xs text-nx-muted">
          مدیریت امنیت حساب کاربری، احراز هویت دومرحله‌ای (TOTP) و نشست‌های فعال
        </p>
      </div>

      {/* Profile Summary */}
      {user && (
        <div className="nx-card rounded-2xl p-5 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="text-base font-bold text-nx-text">{user.full_name}</h2>
            <p className="text-xs text-nx-muted mt-0.5"><LtrValue>{user.email}</LtrValue></p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="gold">نقش: {user.role}</Badge>
            <Badge variant={user.mfa_enabled ? 'profit' : 'warning'}>
              {user.mfa_enabled ? 'MFA فعال' : 'MFA غیرفعال'}
            </Badge>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {/* Password Change */}
        <form onSubmit={handlePasswordChange} className="nx-card rounded-2xl p-5 space-y-3">
          <h2 className="flex items-center gap-2 text-sm font-bold text-nx-text">
            <KeyRound className="h-4 w-4 text-nx-gold" />
            تغییر رمز عبور
          </h2>
          <div>
            <label className="mb-1 block text-xs text-nx-muted">رمز عبور فعلی</label>
            <input
              type="password"
              required
              dir="ltr"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              className="w-full rounded-xl border border-nx-border bg-nx-bg px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-nx-muted">رمز عبور جدید (حداقل ۱۲ کاراکتر)</label>
            <input
              type="password"
              required
              minLength={12}
              dir="ltr"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="w-full rounded-xl border border-nx-border bg-nx-bg px-3 py-2 text-sm"
            />
          </div>
          {pwdMsg && <p className="text-xs text-nx-gold">{pwdMsg}</p>}
          <Button type="submit" size="sm">ذخیره رمز جدید</Button>
        </form>

        {/* MFA Setup */}
        <div className="nx-card rounded-2xl p-5 space-y-3">
          <h2 className="flex items-center gap-2 text-sm font-bold text-nx-text">
            <ShieldCheck className="h-4 w-4 text-nx-gold" />
            احراز هویت دومرحله‌ای (TOTP Authenticator)
          </h2>
          <p className="text-xs leading-6 text-nx-muted">
            برای حفاظت از دسترسی ادمین و معاملات، کلید TOTP را در Google Authenticator یا 1Password ثبت کنید.
          </p>

          {!mfaSecret ? (
            <Button variant="secondary" size="sm" onClick={startMfaSetup}>
              {user?.mfa_enabled ? 'تولید مجدد کلید MFA' : 'فعال‌سازی MFA'}
            </Button>
          ) : (
            <div className="space-y-3 rounded-xl border border-nx-gold/30 bg-nx-bg/70 p-3 text-xs">
              <div>
                <span className="text-nx-muted">کلید مخفی (Secret):</span>
                <div className="mt-1 rounded-lg bg-nx-surface p-2 font-mono text-nx-gold break-all" dir="ltr">
                  {mfaSecret}
                </div>
              </div>
              <div className="text-[11px] text-nx-muted break-all" dir="ltr">{mfaUri}</div>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  dir="ltr"
                  maxLength={6}
                  placeholder="کد ۶ رقمی"
                  value={mfaCode}
                  onChange={(e) => setMfaCode(e.target.value)}
                  className="w-36 rounded-lg border border-nx-border bg-nx-surface px-3 py-1.5 text-center font-mono text-sm"
                />
                <Button size="sm" onClick={verifyMfa}>تأیید و فعال‌سازی</Button>
              </div>
            </div>
          )}
          {mfaMsg && <p className="text-xs text-nx-profit">{mfaMsg}</p>}
        </div>
      </div>

      {/* Active Sessions */}
      <div className="nx-card rounded-2xl p-5">
        <h2 className="mb-3 flex items-center gap-2 text-sm font-bold text-nx-text">
          <Laptop className="h-4 w-4 text-nx-gold" />
          نشست‌های فعال (دستگاه‌های متصل)
        </h2>
        <div className="space-y-2">
          {sessions.map((s) => (
            <div key={s.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-nx-bg/60 p-3 text-xs">
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-nx-text">{(s.user_agent || 'مرورگر').slice(0, 60)}</span>
                  {s.is_current && <Badge variant="profit">نشست فعلی</Badge>}
                </div>
                <div className="mt-0.5 text-[11px] text-nx-muted">
                  IP: <LtrValue>{s.ip_address || '-'}</LtrValue> • ایجاد: {formatDateTimeFa(s.created_at)}
                </div>
              </div>
              {!s.is_current && (
                <Button variant="danger" size="sm" onClick={() => revokeSession(s.id)}>
                  لغو نشست
                </Button>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
