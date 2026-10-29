import React, { useState } from 'react'
import { call, downloadExport } from './api.js'
import { Hash, Icon, Result, clock, sentence } from './ui.jsx'

const EVENTS = ['GRANT', 'WITHDRAW', 'GRANT_REJECTED', 'NOTICE_PUBLISHED', 'ALLOW', 'DENY']

export default function Ledger({ ledger, person, people, onChange }) {
  const [event, setEvent] = useState('')
  const [only, setOnly] = useState(false)
  const [head, setHead] = useState('')
  const [v, setV] = useState(null)
  const [exported, setExported] = useState('')
  const name = people.find((u) => u.user_pid === person)?.name
  const rows = (ledger || []).filter((e) => (!event || e.event === event) && (!only || e.user_pid === person)).slice().reverse()

  const verify = async () => setV((await call('console_verify', { query: { expected_head: head } })).data)
  const exportIt = async (fmt) => setExported(await downloadExport(fmt))
  return (
    <section>
      <h2><Icon name="list" /> Audit log</h2>
      <p className="lede">Every grant, withdrawal, notice change and data request, newest first. Each entry is chained to the one before it.</p>
      <div className="row">
        <label>Show
          <select value={event} onChange={(e) => setEvent(e.target.value)}>
            <option value="">every event</option>{EVENTS.map((x) => <option key={x}>{x}</option>)}</select></label>
        <label className="check-inline"><input type="checkbox" checked={only} onChange={(e) => setOnly(e.target.checked)} /> Only {name}</label>
      </div>
      <div className="row">
        <button onClick={() => exportIt('json')}><Icon name="download" size={16} /> Export JSON</button>
        <button onClick={() => exportIt('csv')}><Icon name="download" size={16} /> Export CSV</button>
      </div>
      {exported && <p className="muted">Exported. Head hash <Hash value={exported} n={24} />. Keep it: verifying against it later detects truncation.</p>}
      <div className="row">
        <input value={head} onChange={(e) => setHead(e.target.value)} placeholder="Optional: head hash from an earlier export" />
        <button className="primary" onClick={verify}><Icon name="shield" size={16} /> Verify integrity</button>
      </div>
      {v && <div className={`banner ${v.valid ? 'ok' : 'deny'}`}>{v.valid
        ? `Chain valid: ${v.entries} entries${v.anchored_to_export ? ', anchored to the export' : ''}.`
        : `Tampering detected${v.first_bad_seq ? ` at entry #${v.first_bad_seq}` : ''}: ${v.reason}.`}</div>}
      <ol className="log">
        {rows.map((e) => (
          <li key={e.seq} className={e.event === 'DENY' || e.event === 'GRANT_REJECTED' ? 'bad' : e.event === 'ALLOW' || e.event === 'GRANT' ? 'ok' : 'neutral'}>
            <div className="when">#{e.seq} &middot; {clock(e.ts)} <Result e={e} /> <b>{e.user_pid || ''}</b> <Hash value={e.notice_hash} n={8} /></div>
            <p>{sentence(e)}</p>
            {e.downstream?.map((d) => <p className="muted" key={d.requester_id}>Told {d.requester_id}: {d.acknowledged ? 'acknowledged' : 'not yet acknowledged'}</p>)}
          </li>))}
      </ol>
    </section>
  )
}
