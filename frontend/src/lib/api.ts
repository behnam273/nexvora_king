let csrfTokenMemory = '';
let authGeneration = 0;

export const SESSION_EXPIRED_EVENT = 'nexvora:session-expired';

export function setCsrfToken(token: string) {
  csrfTokenMemory = token || '';
  authGeneration += 1;
}

export function getCsrfToken(): string {
  return csrfTokenMemory;
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export async function apiFetch<T = unknown>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const method = (options.method || 'GET').toUpperCase();
  const requestGeneration = authGeneration;
  const headers = new Headers(options.headers || {});
  if (!headers.has('Content-Type') && options.body && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method) && csrfTokenMemory) {
    headers.set('X-CSRF-Token', csrfTokenMemory);
  }

  const resp = await fetch(path, {
    ...options,
    method,
    headers,
    credentials: 'include',
  });

  if (!resp.ok) {
    // A protected request can outlive a logout or a new login. Never let its
    // stale 401 invalidate the newer session, and leave login errors in place.
    const authEndpoint = path.split('?')[0];
    if (resp.status === 401 && requestGeneration === authGeneration && csrfTokenMemory &&
        !['/api/v1/auth/login', '/api/v1/auth/register', '/api/v1/auth/logout', '/api/v1/auth/me'].includes(authEndpoint)) {
      window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
    }
    let msg = `خطای ارتباط با سرور (${resp.status})`;
    try {
      const errBody = await resp.json();
      if (errBody?.detail) {
        msg = typeof errBody.detail === 'string' ? errBody.detail : JSON.stringify(errBody.detail);
      }
    } catch {
      // ignore non-json error body
    }
    throw new ApiError(msg, resp.status);
  }

  if (resp.status === 204) {
    return undefined as T;
  }
  return (await resp.json()) as T;
}
