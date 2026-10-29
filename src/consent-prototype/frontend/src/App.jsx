import React, { useEffect, useState } from 'react'
import { call } from './api.js'
import Consent from './Consent.jsx'
import DataRequest from './DataRequest.jsx'
import Notices from './Notices.jsx'
import Ledger from './Ledger.jsx'
import GuidedDemo from './GuidedDemo.jsx'
import { ErrorLine, Icon, usePoll } from './ui.jsx'

export default function App() {
  const [opts, setOpts] = useState(null)
  const [person, setPerson] = useState('u001')
  const [bump, setBump] = useState(0)          // incremented after any action so every panel refreshes at once
  const [err, setErr] = useState('')
  const onChange = () => setBump((b) => b + 1)

  const [purposes] = usePoll(async () => (await call('purposes')).data, 5000, [bump])
  const [ledger] = usePoll(async () => (await call('console_ledger', { query: { limit: 300 } })).data, 3000, [bump])

  useEffect(() => {
    call('console_state')
      .then((r) => (r.ok ? setOpts(r.data) : setErr('The server could not load the people and organizations. Check the server log.')))
      .catch(() => setErr('Cannot reach the API.'))
  }, [])

  return (
    <div className="shell">
      <header className="top">
        <span className="mark"><Icon name="shield" size={22} /></span>
        <div>
          <strong>Consent console</strong>
          <span className="legal">Purpose-based consent under DPDP Act 2023, s.4(1)(a) read with s.6 &middot; synthetic data only</span>
        </div>
      </header>
      {err && <main><ErrorLine msg={err} /></main>}
      {!err && opts && (
        <main className="page">
          <div className="left">
            <Consent person={person} setPerson={setPerson} people={opts.people} ledger={ledger} bump={bump} onChange={onChange} />
            <DataRequest person={person} people={opts.people} requesters={opts.requesters} purposes={purposes} bump={bump} onChange={onChange} />
            <Notices purposes={purposes} onChange={onChange} />
          </div>
          <aside className="right"><Ledger ledger={ledger} person={person} people={opts.people} onChange={onChange} /></aside>
          <div className="full"><GuidedDemo onChange={onChange} /></div>
        </main>
      )}
    </div>
  )
}
