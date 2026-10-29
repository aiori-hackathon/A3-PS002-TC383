import React, { useEffect, useState } from 'react'
import { call } from './api.js'
import { Icon, Pill, REASONS, clock, purposeName, usePoll } from './ui.jsx'

export default function DataRequest({ person, people, requesters, purposes, bump, onChange }) {
  const [rid, setRid] = useState(requesters[0]?.requester_id)
  const req = requesters.find((r) => r.requester_id === rid)
  const [purpose, setPurpose] = useState(req?.allowed_purposes[0])
  const [result, setResult] = useState(null)
  const name = people.find((u) => u.user_pid === person)?.name

  useEffect(() => { setPurpose(req?.allowed_purposes[0]); setResult(null) }, [rid])
  const [revs, reloadR] = usePoll(async () => (await call('console_revocations', { path: { requester_id: rid } })).data, 3000, [rid, bump])

  const send = async () => {
    const r = await call('console_request', { body: { requester_id: rid, user_pid: person, purpose } })
    setResult(r.ok ? { ok: r.data.allowed, status: r.data.http_status, data: r.data } : { ok: false, status: r.status, data: { reason: 'ERROR' } })
    onChange()
  }
  const ack = async (seq) => { await call('console_ack', { path: { requester_id: rid, withdraw_seq: seq } }); reloadR(); onChange() }
  const pending = (revs || []).filter((r) => !r.acknowledged)

  return (
    <section className="card">
      <h2><Icon name="send" /> 2. Data request</h2>
      <p className="lede">A requesting service asks the data-sharing API for {name}'s data. Consent is checked at the moment the request arrives.</p>
      <div className="row">
        <label>Requesting service
          <select value={rid} onChange={(e) => setRid(e.target.value)}>
            {requesters.map((r) => <option key={r.requester_id} value={r.requester_id}>{r.name}</option>)}</select></label>
        <label>Purpose
          <select value={purpose} onChange={(e) => setPurpose(e.target.value)}>
            {purposes?.map((p) => <option key={p.purpose} value={p.purpose}>{purposeName(p.purpose)}</option>)}</select></label>
        <button className="primary" onClick={send}><Icon name="send" size={16} /> Request data</button>
      </div>
      <p className="muted">{req?.name} is registered for: {req?.allowed_purposes.map(purposeName).join(', ')}.</p>
      {result && (
        <div className={`banner ${result.ok ? 'ok' : 'deny'}`}>
          <b>HTTP {result.status}: {result.ok ? 'allowed' : 'refused'}.</b> {REASONS[result.data.reason]}
          {result.ok && <pre>{JSON.stringify(result.data.data, null, 2)}</pre>}
        </div>)}
      <div className={`panel ${pending.length ? 'alert' : ''}`}>
        <h3><Icon name="bell" size={17} /> Withdrawal notices for {req?.name} {pending.length > 0 && <Pill kind="warn">{pending.length} waiting</Pill>}</h3>
        {revs?.length === 0 && <p className="muted">None. When a person withdraws consent for data this service received, it is told here and must stop processing it.</p>}
        <ul className="revs">
          {revs?.map((r) => (
            <li key={r.withdraw_seq}>
              <span><b>{r.user_pid}</b> withdrew consent for {purposeName(r.purpose)} at {clock(r.ts)}. {r.instruction}</span>
              {r.acknowledged ? <Pill kind="allow">Acknowledged</Pill> : <button className="primary" onClick={() => ack(r.withdraw_seq)}><Icon name="check" size={16} /> Acknowledge and stop</button>}
            </li>))}
        </ul>
      </div>
    </section>
  )
}
