import React, { useState } from 'react'
import { call } from './api.js'
import { Icon, Pill } from './ui.jsx'

const D = { user: 'u001', org: 'analytics-co', purpose: 'analytics' }

export default function GuidedDemo({ onChange }) {
  const [log, setLog] = useState([])
  const [i, setI] = useState(0)
  const [busy, setBusy] = useState(false)

  const ask = async () => call('console_request', { body: { requester_id: D.org, user_pid: D.user, purpose: D.purpose } })
  const agree = async () => {
    const n = (await call('purposes')).data.find((p) => p.purpose === D.purpose).notice
    return call('console_grant', { path: { user_pid: D.user }, body: { purpose: D.purpose, notice_hash: n.hash } })
  }
  const STEPS = [
    ['Before any valid consent', 'Analytics Co asks for Asha\'s analytics data with no valid consent on record, so it is refused. (For a clean run, restart with a fresh database: see README.)', ask],
    ['Asha agrees', 'She agrees to notice v1. The receipt records the notice hash she saw (s.5 notice, s.6(1) specific consent).', agree],
    ['Data is shared', 'The same request is now allowed, and returns only the fields this purpose covers.', ask],
    ['Asha withdraws', 'One action, no reason needed (s.6(4)). Earlier processing stays lawful and visible in the log (s.6(5)).',
      async () => call('console_withdraw', { path: { user_pid: D.user }, body: { purpose: D.purpose } })],
    ['Request after withdrawal', 'Refused immediately. Analytics Co also has a withdrawal notice to acknowledge (s.6(6)).', ask],
    ['Asha agrees again, then the notice changes', 'A new notice v2 is published for analytics.', async () => {
      await agree()
      return call('console_publish', { body: { purpose: D.purpose, text: 'Notice v2. Data: age band, daily step count. Purpose: analytics. Now retained for 24 months. Withdraw any time. Contact: privacy@example.test.' } })
    }],
    ['Request under the old consent', 'Refused: the notice changed after Asha agreed, so her consent no longer covers it.', ask],
    ['Check the log', 'Recompute the whole hash chain. Every step above is in it, and editing any entry would break it (s.6(10) evidence).',
      async () => call('console_verify')],
  ]
  const run = async () => {
    setBusy(true)
    const r = await STEPS[i][2]()
    setLog((l) => [{ title: STEPS[i][0], note: STEPS[i][1], r }, ...l])
    setI(i + 1); setBusy(false); onChange()
  }
  const verdict = (r) => {
    const d = r.data
    if (d?.allowed === true) return <Pill kind="allow">Allowed</Pill>
    if (d?.allowed === false) return <Pill kind="deny">Refused: {d.reason}</Pill>
    if (d?.valid !== undefined) return <Pill kind={d.valid ? 'allow' : 'deny'}>{d.valid ? `Chain valid, ${d.entries} entries` : 'Tampering detected'}</Pill>
    return <Pill kind={r.ok ? 'info' : 'deny'}>{r.ok ? 'Done' : `Error ${r.status}`}</Pill>
  }
  return (
    <section className="card">
      <h2><Icon name="play" /> Lifecycle walkthrough</h2>
      <p className="lede">Eight steps on the running system: grant, share, withdraw, refused, notice change. Watch the panels above update after each step.</p>
      <div className="row">
        <button className="primary" onClick={run} disabled={busy || i >= STEPS.length}>
          <Icon name="play" size={16} /> {i >= STEPS.length ? 'Walkthrough finished' : `Step ${i + 1} of ${STEPS.length}: ${STEPS[i][0]}`}</button>
        {i > 0 && <button onClick={() => { setI(0); setLog([]) }}>Clear and restart the steps</button>}
      </div>
      <ol className="demo">
        {log.map((s, k) => <li key={k}><div className="when"><b>{s.title}</b> {verdict(s.r)}</div><p>{s.note}</p></li>)}
      </ol>
    </section>
  )
}
