import React, { useCallback, useEffect, useRef, useState } from 'react'

/** Runs `fn` now and every `ms` milliseconds; returns [data, reload]. Keeps screens live without refresh. */
export function usePoll(fn, ms = 3000, deps = []) {
  const [data, setData] = useState(null)
  const ref = useRef(fn)
  ref.current = fn
  const load = useCallback(async () => { try { setData(await ref.current()) } catch { /* keep last data */ } }, [])
  useEffect(() => {
    load()
    const t = setInterval(load, ms)
    return () => clearInterval(t)
  }, [load, ms, ...deps])
  return [data, load]
}

export const PURPOSE_LABEL = { analytics: 'Analytics', marketing: 'Marketing e-mails', research_sharing: 'Health research' }
export const purposeName = (p) => PURPOSE_LABEL[p] || p
export const short = (h, n = 10) => (h ? h.slice(0, n) : '')
export const clock = (ts) => (ts ? new Date(ts).toLocaleTimeString([], { hour12: false }) : '')
export const stamp = (ts) => (ts ? new Date(ts).toLocaleString([], { hour12: false }) : '')

export const REASONS = {
  CONSENT_VALID: 'Valid consent on record.',
  REQ_AUTH: 'The requester could not be identified (missing or wrong API key).',
  REQ_PURPOSE: 'This organization is not registered for that purpose.',
  NO_NOTICE: 'No notice has been published for this purpose.',
  NO_CONSENT: 'No consent on record for this person and purpose.',
  CONSENT_WITHDRAWN: 'The person withdrew their consent.',
  NOTICE_STALE: 'The notice changed after the person agreed. Fresh consent is needed.',
  ERROR: 'The request could not be checked safely, so it was refused.',
  NOTICE_HASH_MISMATCH: 'The person was shown an outdated notice.',
  HASH_MISSING: 'The grant did not say which notice the person saw.',
}

export function Pill({ kind = 'none', children }) {
  return <span className={`pill ${kind}`}>{children}</span>
}

export function Hash({ value, n = 12 }) {
  return value ? <code className="hash" title={value}>{short(value, n)}</code> : null
}

export function Result({ e }) {
  if (e.event === 'ALLOW') return <Pill kind="allow">Allowed</Pill>
  if (e.event === 'DENY') return <Pill kind="deny">Refused</Pill>
  if (e.event === 'GRANT') return <Pill kind="allow">Agreed</Pill>
  if (e.event === 'WITHDRAW') return <Pill kind="warn">Withdrawn</Pill>
  if (e.event === 'GRANT_REJECTED') return <Pill kind="deny">Not recorded</Pill>
  return <Pill kind="info">Notice</Pill>
}

const fieldsOf = (d) => (d || '').replace('fields=', '').split(',').filter(Boolean).join(', ')
const who = (actor) => (actor || '').replace('requester:', '').replace('user:', '')

/** One plain-English sentence per ledger entry, so no explanation is needed to read the screen. */
export function sentence(e) {
  const p = purposeName(e.purpose)
  switch (e.event) {
    case 'GRANT': return `Agreed to share data for ${p} (${e.detail || 'notice recorded'}).`
    case 'WITHDRAW': return `Withdrew consent for ${p}. Processing for this purpose must stop now.`
    case 'GRANT_REJECTED': return `Agreement for ${p} was not recorded. ${REASONS[e.reason] || ''}`
    case 'NOTICE_PUBLISHED': return `New notice for ${p} published (${e.detail}). Earlier consent to this purpose needs renewing.`
    case 'ALLOW': return `${who(e.actor)} received ${fieldsOf(e.detail)} for ${p}. ${REASONS.CONSENT_VALID}`
    case 'DENY': return `${who(e.actor)} was refused ${p} data. ${REASONS[e.reason] || e.reason}`
    default: return e.event
  }
}

const ICONS = {
  shield: ['M12 3l7 3v5c0 4.4-3 8.1-7 10-4-1.9-7-5.6-7-10V6z', 'M9 12l2 2 4-4'],
  check: ['M5 12.5l4.2 4.2L19 7'],
  x: ['M6 6l12 12', 'M18 6L6 18'],
  user: ['M12 4.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 1 0 0-7z', 'M5 20c.4-3.3 3.3-5.5 7-5.5s6.6 2.2 7 5.5'],
  send: ['M4 12l16-8-6 16-3-6.5z', 'M11 13.5L20 4'],
  file: ['M7 3h7l4 4v14H7z', 'M14 3v4h4', 'M10 12h5', 'M10 16h5'],
  list: ['M8 6h12', 'M8 12h12', 'M8 18h12', 'M4 6h.01', 'M4 12h.01', 'M4 18h.01'],
  play: ['M8 5.5l11 6.5-11 6.5z'],
  download: ['M12 4v11', 'M7.5 11l4.5 4.5 4.5-4.5', 'M5 20h14'],
  bell: ['M6 16v-5a6 6 0 0 1 12 0v5l2 2H4z', 'M10 21a2 2 0 0 0 4 0'],
  lock: ['M6 11h12v9H6z', 'M8.5 11V8a3.5 3.5 0 0 1 7 0v3'],
}

/** Simple line icon (decorative: hidden from screen readers; the text next to it carries the meaning). */
export function Icon({ name, size = 18 }) {
  return (
    <svg className="icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      {ICONS[name].map((d, i) => <path key={i} d={d} />)}
    </svg>
  )
}

export function Notice({ text }) {
  return <p className="notice">{text}</p>
}

export function ErrorLine({ msg }) {
  return msg ? <p className="error" role="alert">{msg}</p> : null
}
