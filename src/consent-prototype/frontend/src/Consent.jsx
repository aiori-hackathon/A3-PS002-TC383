import React, { useState } from 'react'
import { call } from './api.js'
import { ErrorLine, Hash, Icon, Notice, Pill, REASONS, clock, purposeName, stamp, usePoll } from './ui.jsx'

const STATUS = {
  none: ['none', 'Not agreed'], granted: ['allow', 'Agreed'],
  withdrawn: ['warn', 'Withdrawn'], stale: ['stale', 'Notice changed'],
}

function PurposeCard({ c, ledger, person, act, busy }) {
  const [kind, label] = STATUS[c.status]
  const lastWithdraw = (ledger || []).filter((e) => e.event === 'WITHDRAW' && e.user_pid === person && e.purpose === c.purpose).pop()
  return (
    <article className={`purpose ${c.status}`}>
      <div className="purpose-head">
        <div><h3>{purposeName(c.purpose)}</h3><p className="muted">{c.description}</p></div>
        <Pill kind={kind}>{label}</Pill>
      </div>
      <dl className="facts">
        <dt>Legal basis</dt><dd>{c.legal_basis}</dd>
        <dt>Data covered</dt><dd>{c.fields.map((f) => <span className="chip" key={f}>{f.replaceAll('_', ' ')}</span>)}</dd>
        <dt>Notice</dt><dd>version {c.notice?.version} <Hash value={c.notice?.hash} /></dd>
      </dl>
      <Notice text={c.notice?.text} />
      {c.status === 'granted' && c.receipt && (
        <div className="receipt" aria-label="Consent receipt">
          <b><Icon name="check" size={15} /> Consent receipt</b>
          <span>Agreed on {stamp(c.receipt.ts)} to notice v{c.receipt.notice_version}</span>
          <span>Notice <Hash value={c.receipt.notice_hash} n={16} /> &middot; ledger entry #{c.receipt.seq} <Hash value={c.receipt.entry_hash} n={16} /></span>
        </div>)}
      {c.status === 'withdrawn' && (
        <div className="banner warn">
          <Icon name="lock" size={15} /> <b>Processing stopped.</b> Requests for this purpose are refused from {clock(lastWithdraw?.ts)}.
          {lastWithdraw?.downstream?.length > 0 && (
            <ul>{lastWithdraw.downstream.map((d) => (
              <li key={d.requester_id}>{d.requester_id} was told to stop: {d.acknowledged ? 'acknowledged' : 'waiting for acknowledgement'}</li>))}</ul>)}
        </div>)}
      {c.status === 'stale' && (
        <div className="banner stale"><b>The notice changed.</b> The earlier agreement (v{c.consented_version}) no longer applies, so requests are refused until the new notice is agreed.</div>)}
      <div className="actions">
        {c.status === 'granted'
          ? <button className="danger" disabled={busy} onClick={() => act('withdraw', c)}><Icon name="x" size={16} /> Withdraw consent</button>
          : <button className="primary" disabled={busy} onClick={() => act('grant', c)}>
              <Icon name="check" size={16} /> {c.status === 'stale' ? 'Agree to the updated notice' : 'Agree to this notice'}</button>}
        <span className="muted">{c.status === 'granted' ? 'One click, no reason needed.' : 'Nothing is agreed until this is pressed.'}</span>
      </div>
    </article>
  )
}

export default function Consent({ person, setPerson, people, ledger, bump, onChange }) {
  const [consents, reload] = usePoll(async () => (await call('console_consents', { path: { user_pid: person } })).data, 3000, [person, bump])
  const [timeline] = usePoll(async () => { const r = await call('console_timeline', { path: { user_pid: person } }); return r.ok ? r.data : null }, 4000, [person, bump])
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const act = async (kind, c) => {
    setBusy(true); setErr('')
    const r = kind === 'grant'
      ? await call('console_grant', { path: { user_pid: person }, body: { purpose: c.purpose, notice_hash: c.notice?.hash } })
      : await call('console_withdraw', { path: { user_pid: person }, body: { purpose: c.purpose } })
    if (!r.ok) setErr(REASONS[r.data?.error] || r.data?.message || 'That did not work.')
    await reload(); onChange(); setBusy(false)
  }
  return (
    <section className="card">
      <div className="section-head">
        <h2><Icon name="user" /> 1. Consent</h2>
        <label className="inline">Person
          <select value={person} onChange={(e) => setPerson(e.target.value)}>
            {people.map((u) => <option key={u.user_pid} value={u.user_pid}>{u.name} ({u.user_pid})</option>)}
          </select></label>
      </div>
      <p className="lede">Each purpose is separate. Data is shared only for a purpose that has been agreed, under the notice that was shown.</p>
      {timeline && (
        <p className={`assure ${timeline.server_check.chain_valid ? 'ok' : 'bad'}`}>
          <Icon name="shield" size={16} /> {timeline.server_check.chain_valid
            ? `Ledger intact: ${timeline.server_check.entries} entries checked by the server.`
            : 'Ledger check failed. Contact the administrator.'} <span className="muted">Full verification needs the export.</span>
        </p>)}
      <ErrorLine msg={err} />
      {consents?.map((c) => <PurposeCard key={c.purpose} c={c} ledger={ledger} person={person} act={act} busy={busy} />)}
    </section>
  )
}
