import React from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { AppShell } from './components/layout/AppShell';
import { LoginPage } from './pages/LoginPage';
import { DashboardPage } from './pages/DashboardPage';
import { LiveTradesPage } from './pages/LiveTradesPage';
import { TradeDetailPage } from './pages/TradeDetailPage';
import { TradeHistoryPage } from './pages/TradeHistoryPage';
import { AnalyticsPage } from './pages/AnalyticsPage';
import { NewsPage } from './pages/NewsPage';
import { CalendarPage } from './pages/CalendarPage';
import { MarketOverviewPage } from './pages/MarketOverviewPage';
import { NotificationsPage } from './pages/NotificationsPage';
import { SettingsPage } from './pages/SettingsPage';
import { AdminPage } from './pages/AdminPage';

const RequireAuth: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-nx-bg text-sm text-nx-gold">
        در حال بارگذاری NEXVORA...
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
};

const RequireAdmin: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user } = useAuth();
  if (!user || !['SUPER_ADMIN', 'ADMIN'].includes(user.role)) {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
};

export const App: React.FC = () => {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            element={
              <RequireAuth>
                <AppShell />
              </RequireAuth>
            }
          >
            <Route path="/" element={<DashboardPage />} />
            <Route path="/trades/live" element={<LiveTradesPage />} />
            <Route path="/trades/history" element={<TradeHistoryPage />} />
            <Route path="/trades/:id" element={<TradeDetailPage />} />
            <Route path="/analytics" element={<AnalyticsPage />} />
            <Route path="/news" element={<NewsPage />} />
            <Route path="/calendar" element={<CalendarPage />} />
            <Route path="/market" element={<MarketOverviewPage />} />
            <Route path="/notifications" element={<NotificationsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route
              path="/admin"
              element={
                <RequireAdmin>
                  <AdminPage />
                </RequireAdmin>
              }
            />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
};

export default App;
