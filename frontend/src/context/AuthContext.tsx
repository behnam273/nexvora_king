import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { apiFetch, ApiError, setCsrfToken, SESSION_EXPIRED_EVENT } from '../lib/api';
import { createRealtimeClient, WsEvent, WsStatus } from '../lib/ws';
import type { User } from '../types';

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  wsStatus: WsStatus;
  lastWsEvent: WsEvent | null;
  isOnline: boolean;
  login: (email: string, password: string, mfaCode?: string) => Promise<void>;
  register: (email: string, fullName: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshMe: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [wsStatus, setWsStatus] = useState<WsStatus>('disconnected');
  const [lastWsEvent, setLastWsEvent] = useState<WsEvent | null>(null);
  const [isOnline, setIsOnline] = useState(typeof navigator !== 'undefined' ? navigator.onLine : true);

  useEffect(() => {
    const onOnline = () => setIsOnline(true);
    const onOffline = () => setIsOnline(false);
    window.addEventListener('online', onOnline);
    window.addEventListener('offline', onOffline);
    return () => {
      window.removeEventListener('online', onOnline);
      window.removeEventListener('offline', onOffline);
    };
  }, []);

  const refreshMe = useCallback(async () => {
    try {
      const res = await apiFetch<{ user: User; csrf_token: string }>('/api/v1/auth/me');
      setCsrfToken(res.csrf_token);
      setUser(res.user);
    } catch {
      setUser(null);
      setCsrfToken('');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const onSessionExpired = () => {
      setCsrfToken('');
      setUser(null);
      setLastWsEvent(null);
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, onSessionExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onSessionExpired);
  }, []);

  useEffect(() => {
    refreshMe();
  }, [refreshMe]);

  useEffect(() => {
    if (!user) {
      setWsStatus('disconnected');
      return;
    }
    const client = createRealtimeClient(
      (ev) => setLastWsEvent(ev),
      (st) => setWsStatus(st)
    );
    return () => client.close();
  }, [user]);

  const confirmSession = async () => {
    try {
      return await apiFetch<{ user: User; csrf_token: string }>('/api/v1/auth/me');
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        throw new Error('مرورگر کوکی نشست را ذخیره نکرد. پیش‌نمایش را در یک تب مستقل باز کنید یا اجازهٔ کوکی را فعال کنید و دوباره وارد شوید.');
      }
      throw error;
    }
  };

  const login = async (email: string, password: string, mfaCode?: string) => {
    await apiFetch<{ user: User; csrf_token: string }>('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password, mfa_code: mfaCode || undefined }),
    });
    const confirmed = await confirmSession();
    setCsrfToken(confirmed.csrf_token);
    setUser(confirmed.user);
  };

  const register = async (email: string, fullName: string, password: string) => {
    await apiFetch<{ user: User; csrf_token: string }>('/api/v1/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, full_name: fullName, password }),
    });
    const confirmed = await confirmSession();
    setCsrfToken(confirmed.csrf_token);
    setUser(confirmed.user);
  };

  const logout = async () => {
    try {
      await apiFetch('/api/v1/auth/logout', { method: 'POST' });
    } catch {
      // ignore if already expired
    } finally {
      setCsrfToken('');
      setUser(null);
      // Security requirement: clear SW caches on logout / account switching
      if ('serviceWorker' in navigator && navigator.serviceWorker.controller) {
        navigator.serviceWorker.controller.postMessage({ type: 'CLEAR_CACHES' });
      }
      if ('caches' in window) {
        caches.keys().then((keys) => keys.forEach((k) => caches.delete(k))).catch(() => {});
      }
    }
  };

  return (
    <AuthContext.Provider
      value={{ user, loading, wsStatus, lastWsEvent, isOnline, login, register, logout, refreshMe }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
