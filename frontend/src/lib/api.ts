let csrfTokenMemory = '';

export function setCsrfToken(token: string) {
  csrfTokenMemory = token || '';
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
