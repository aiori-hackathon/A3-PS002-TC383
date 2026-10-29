import React, { useState } from 'react'
import { call } from './api.js'
import { Icon, purposeName } from './ui.jsx'

export default function Notices({ purposes, onChange }) {
  const [purpose, setPurpose] = useState('analytics')
  const [text, setText] = useState('')
  const [msg, setMsg] = useState(null)
  const publish = async () => {
    const r = await call('console_publish', { body: { purpose, text } })
    setMsg(r.ok ? { ok: true, t: `Published v${r.data.version}. ${r.data.users_needing_reconsent} people must agree again.` } : { ok: false, t: r.data.message })
    if (r.ok) setText('')
    onChange()
  }
  return (
    <section className="card">
      <h2><Icon name="file" /> 3. Publish a new notice</h2>
      <p className="lede">A new version replaces the current one for this purpose only. Anyone who agreed earlier is refused until they agree to the new text.</p>
      <div className="row"><label>Purpose
        <select value={purpose} onChange={(e) => setPurpose(e.target.value)}>
          {purposes?.map((p) => <option key={p.purpose} value={p.purpose}>{purposeName(p.purpose)}</option>)}</select></label></div>
      <textarea rows="4" value={text} onChange={(e) => setText(e.target.value)} placeholder="Notice text: the data, the purpose, how to withdraw, who to contact." />
      <div className="row"><button className="primary" onClick={publish} disabled={!text.trim()}><Icon name="file" size={16} /> Publish notice</button></div>
      {msg && <div className={`banner ${msg.ok ? 'ok' : 'deny'}`}>{msg.t}</div>}
    </section>
  )
}
