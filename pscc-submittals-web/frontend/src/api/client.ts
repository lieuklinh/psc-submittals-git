// Base URL: empty string means "same origin, use the Vite dev proxy"
// (dev) or a same-domain deployment (prod, e.g. Azure Static Web Apps
// routing /api to a linked backend). Set VITE_API_URL to point at a
// separately-hosted backend instead.
const API_BASE = import.meta.env.VITE_API_URL || ''

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

function authHeaders(): Record<string, string> {
  const email = localStorage.getItem('user_email')
  const name = localStorage.getItem('user_name')
  const headers: Record<string, string> = {}
  if (email) headers['X-User-Email'] = email
  if (name) headers['X-User-Name'] = name
  return headers
}

async function handle<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let detail = resp.statusText
    try {
      const data = await resp.json()
      detail = data.detail || JSON.stringify(data)
    } catch {
      // ignore — use statusText
    }
    throw new ApiError(resp.status, typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  if (resp.status === 204) return undefined as T
  const contentType = resp.headers.get('content-type') || ''
  if (contentType.includes('application/json')) {
    return resp.json()
  }
  return undefined as T
}

export async function apiGet<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, { headers: authHeaders() })
  return handle<T>(resp)
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  return handle<T>(resp)
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: 'PATCH',
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return handle<T>(resp)
}

export async function apiDelete<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, { method: 'DELETE', headers: authHeaders() })
  return handle<T>(resp)
}

export async function apiUpload<T>(
  path: string, file: File, fieldName = 'file', extraFields: Record<string, string> = {},
): Promise<T> {
  const form = new FormData()
  form.append(fieldName, file)
  for (const [key, value] of Object.entries(extraFields)) form.append(key, value)
  const resp = await fetch(`${API_BASE}${path}`, { method: 'POST', headers: authHeaders(), body: form })
  return handle<T>(resp)
}

export async function apiDownload(path: string): Promise<Blob> {
  const resp = await fetch(`${API_BASE}${path}`, { headers: authHeaders() })
  if (!resp.ok) throw new ApiError(resp.status, resp.statusText)
  return resp.blob()
}
