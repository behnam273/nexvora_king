export type WsStatus = 'connected' | 'reconnecting' | 'disconnected';

export interface WsEvent {
  type: string;
  data?: unknown;
}

export function createRealtimeClient(
  onMessage: (ev: WsEvent) => void,
  onStatusChange: (status: WsStatus) => void
) {
  let ws: WebSocket | null = null;
  let closedByUser = false;
  let retryMs = 1500;
  let pingTimer: number | null = null;
  let reconnectTimer: number | null = null;

  const connect = () => {
    if (closedByUser) return;
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${proto}//${window.location.host}/ws/realtime`;
    try {
      ws = new WebSocket(url);
    } catch {
      onStatusChange('disconnected');
      return;
    }

    ws.onopen = () => {
      retryMs = 1500;
      onStatusChange('connected');
      pingTimer = window.setInterval(() => {
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send('ping');
        }
      }, 25000);
    };

    ws.onmessage = (e) => {
      try {
        const parsed = JSON.parse(e.data) as WsEvent;
        onMessage(parsed);
      } catch {
        // ignore malformed payloads
      }
    };

    ws.onclose = () => {
      if (pingTimer) window.clearInterval(pingTimer);
      if (closedByUser) {
        onStatusChange('disconnected');
        return;
      }
      onStatusChange('reconnecting');
      reconnectTimer = window.setTimeout(() => {
        retryMs = Math.min(retryMs * 1.6, 15000);
        connect();
      }, retryMs);
    };

    ws.onerror = () => {
      ws?.close();
    };
  };

  connect();

  return {
    close() {
      closedByUser = true;
      if (pingTimer) window.clearInterval(pingTimer);
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      ws?.close();
    },
  };
}
