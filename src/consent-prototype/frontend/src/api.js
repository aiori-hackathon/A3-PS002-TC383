import { operations } from './api.generated.js'

/** Calls an operation from the generated spec. Returns { status, data } and never throws on HTTP errors. */
export async function call(op, { path = {}, query, body, headers = {} } = {}) {
  const def = operations[op]
  if (!def) throw new Error(`unknown operation ${op}`)
  let url = def.path.replace(/\{(\w+)\}/g, (_, k) => encodeURIComponent(path[k]))
  if (query) url += '?' + new URLSearchParams(Object.entries(query).filter(([, v]) => v)).toString()
  const res = await fetch(url, {
    method: def.method,
    headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), ...headers },
    body: body ? JSON.stringify(body) : undefined,
  })
  const text = await res.text()
  let data = null
  try { data = JSON.parse(text) } catch { data = text }
  return { status: res.status, ok: res.ok, data, headers: res.headers }
}

/** Downloads the ledger export and returns its head hash (sent in a response header). */
export async function downloadExport(fmt) {
  const res = await fetch(`/api/console/export?format=${fmt}`)
  const blob = await res.blob()
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `audit_export.${fmt}`
  a.click()
  URL.revokeObjectURL(a.href)
  return res.headers.get('X-Ledger-Head-Hash')
}
