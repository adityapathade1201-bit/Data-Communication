export class ApiError extends Error {}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      const d = body?.detail
      msg = typeof d === 'string' ? d : d ? JSON.stringify(d) : msg
    } catch { /* keep default message */ }
    throw new ApiError(msg)
  }
  return (await res.json()) as T
}

export async function get<T>(path: string): Promise<T> {
  return handle<T>(await fetch(path))
}

export async function post<T>(path: string, body: unknown): Promise<T> {
  return handle<T>(await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }))
}

export function wsUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}/ws/simulate`
}
