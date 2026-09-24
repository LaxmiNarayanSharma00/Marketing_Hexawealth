import { useEffect, useState } from 'react'
import { api } from './api'
import SessionsPage from './pages/SessionsPage'
import SourcesPage from './pages/SourcesPage'
import AutomationsPage from './pages/AutomationsPage'

type View = 'sessions' | 'sources' | 'automations'

export default function App() {
  const [view, setView] = useState<View>('sessions')
  const [ready, setReady] = useState(0)
  const [sessionTotal, setSessionTotal] = useState(0)
  const [sourceCount, setSourceCount] = useState(0)
  const [runCount, setRunCount] = useState(0)

  useEffect(() => {
    api
      .listSessions()
      .then((d) => {
        setSessionTotal(d.sessions.length)
        setReady(d.sessions.filter((s) => s.has_storage_state).length)
      })
      .catch(() => {})
    api
      .listSources()
      .then((d) => setSourceCount(d.sources.length))
      .catch(() => {})
    api
      .listAutomations()
      .then((d) => setRunCount(d.runs.length))
      .catch(() => {})
  }, [view])

  const railPrimary =
    view === 'sessions' ? ready : view === 'sources' ? sourceCount : runCount
  const railPrimaryLabel =
    view === 'sessions' ? 'ready' : view === 'sources' ? 'sources' : 'runs'
  const railTotal =
    view === 'sessions' ? sessionTotal : view === 'sources' ? sourceCount : runCount

  return (
    <div className="shell">
      <aside className="rail" aria-label="Product navigation">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            HX
          </div>
          <div>
            <div className="brand-name">Hexawealth</div>
            <div className="brand-sub">Marketing Agents</div>
          </div>
        </div>

        <nav className="nav">
          <p className="nav-label">Pipeline</p>
          <button
            type="button"
            className={`nav-item${view === 'sessions' ? ' active' : ''}`}
            onClick={() => setView('sessions')}
          >
            <span className="nav-step">01</span>
            <span>
              <strong>Sessions</strong>
              <em>LinkedIn cookie vault</em>
            </span>
          </button>
          <button
            type="button"
            className={`nav-item${view === 'sources' ? ' active' : ''}`}
            onClick={() => setView('sources')}
          >
            <span className="nav-step">02</span>
            <span>
              <strong>Sources</strong>
              <em>Company · Influencer · Individual</em>
            </span>
          </button>
          <button
            type="button"
            className={`nav-item${view === 'automations' ? ' active' : ''}`}
            onClick={() => setView('automations')}
          >
            <span className="nav-step">03</span>
            <span>
              <strong>Automations</strong>
              <em>Fetch · Build Connection</em>
            </span>
          </button>
        </nav>

        <div className="rail-foot">
          <div className="rail-stat">
            <span>{railPrimary}</span>
            <small>{railPrimaryLabel}</small>
          </div>
          <div className="rail-stat">
            <span>{railTotal}</span>
            <small>total</small>
          </div>
        </div>
      </aside>

      <main className="main">
        {view === 'sessions' && (
          <SessionsPage
            onStats={(r, t) => {
              setReady(r)
              setSessionTotal(t)
            }}
          />
        )}
        {view === 'sources' && <SourcesPage onCount={setSourceCount} />}
        {view === 'automations' && <AutomationsPage onCount={setRunCount} />}
      </main>
    </div>
  )
}
