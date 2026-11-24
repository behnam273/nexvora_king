import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { apiFetch, setCsrfToken } from '../lib/api';
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

  const login = async (email: string, password: string, mfaCode?: string) => {
    const res = await apiFetch<{ user: User; csrf_token: string }>('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password, mfa_code: mfaCode || undefined }),
    });
    setCsrfToken(res.csrf_token);
    setUser(res.user);
  };

  const register = async (email: string, fullName: string, password: string) => {
    const res = await apiFetch<{ user: User; csrf_token: string }>('/api/v1/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, full_name: fullName, password }),
    });
    setCsrfToken(res.csrf_token);
    setUser(res.user);
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
