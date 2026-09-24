import { FormEvent, useEffect, useState } from 'react'
import {
  api,
  pollAutomation,
  type AutomationRun,
  type Profile,
  type Session,
  type Source,
} from '../api'

type Kind = 'company_people_fetch' | 'build_connection' | 'brand_engage'

const BRAND_SOURCES = [
  'https://www.linkedin.com/company/hexawealth/posts/',
  'https://www.linkedin.com/in/abhinav-singhvi-1a429233/',
  'https://www.linkedin.com/in/abhinav-swaroop-cfa-8002a015/',
  'https://www.linkedin.com/in/vinayak-gandhi-cfa-b7559b194/',
]

type Props = {
  onCount?: (n: number) => void
}

export default function AutomationsPage({ onCount }: Props) {
  const [kind, setKind] = useState<Kind>('company_people_fetch')
  const [sessions, setSessions] = useState<Session[]>([])
  const [companies, setCompanies] = useState<Source[]>([])
  const [runs, setRuns] = useState<AutomationRun[]>([])
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [pendingCount, setPendingCount] = useState(0)

  const [sessionName, setSessionName] = useState('')
  const [sourceId, setSourceId] = useState('')
  const [maxConnections, setMaxConnections] = useState(10)
  const [maxRequests, setMaxRequests] = useState(10)

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const [logs, setLogs] = useState<string[]>([])
  const [activeRunId, setActiveRunId] = useState<string | null>(null)

  const loggedIn = sessions.filter((s) => s.has_storage_state)

  const runLabel =
    kind === 'build_connection'
      ? 'connect'
      : kind === 'brand_engage'
        ? 'engage'
        : 'fetch'

  const refresh = async (active: Kind = kind) => {
    const [s, c, r, allProfiles] = await Promise.all([
      api.listSessions(),
      api.listSources('company_peoples'),
      api.listAutomations(active),
      api.listProfiles(),
    ])
    setSessions(s.sessions)
    setCompanies(c.sources)
    setRuns(r.runs)
    const allRuns = await api.listAutomations()
    onCount?.(allRuns.runs.length)

    const pending = allProfiles.profiles.filter((p) => {
      const st = (p.connection_status || 'none').toLowerCase()
      return !['pending', 'connected', 'sent', 'self'].includes(st)
    }).length
    setPendingCount(pending)

    if (!sessionName) {
      const first = s.sessions.find((x) => x.has_storage_state)
      if (first) setSessionName(first.name)
    }
    if (!sourceId && c.sources[0]) setSourceId(c.sources[0].id)
  }

  useEffect(() => {
    setError('')
    setInfo('')
    setLogs([])
    setProfiles([])
    refresh(kind).catch((e) => setError(String(e.message || e)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind])

  useEffect(() => {
    if (!info) return
    const t = window.setTimeout(() => setInfo(''), 4500)
    return () => window.clearTimeout(t)
  }, [info])

  const loadProfilesFor = async (run: AutomationRun) => {
    if (run.kind === 'company_people_fetch') {
      const data = await api.listProfiles({ automation_id: run.id })
      setProfiles(data.profiles)
    } else {
      setProfiles([])
    }
  }

  const onActivateFetch = async (e: FormEvent) => {
    e.preventDefault()
    if (!sessionName || !sourceId) return
    setBusy(true)
    setError('')
    setInfo('')
    setLogs([])
    setProfiles([])
    try {
      const run = await api.activateCompanyPeople({
        session_name: sessionName,
        source_id: sourceId,
        max_connections: maxConnections,
      })
      setActiveRunId(run.id)
      setInfo(`Company People Fetch started for ${run.company}.`)
      const final = await pollAutomation(run.id, (row) => setLogs(row.logs || []))
      if (final.status === 'error') {
        setError(final.error || 'Automation failed')
        setInfo('')
      } else {
        const scraped = final.result?.scraped ?? 0
        const skipped = final.result?.skipped ?? 0
        setInfo(
          `Finished · scraped ${scraped}` +
            (skipped ? ` · skipped ${skipped} already saved` : '') +
            (final.result?.failed ? ` · ${final.result.failed} failed` : ''),
        )
        await loadProfilesFor(final)
      }
      await refresh()
    } catch (err: unknown) {
      setError(String((err as Error).message || err))
    } finally {
      setBusy(false)
      setActiveRunId(null)
    }
  }

  const onActivateConnect = async (e: FormEvent) => {
    e.preventDefault()
    if (!sessionName) return
    setBusy(true)
    setError('')
    setInfo('')
    setLogs([])
    setProfiles([])
    try {
      const run = await api.activateBuildConnection({
        session_name: sessionName,
        max_requests: maxRequests,
      })
      setActiveRunId(run.id)
      setInfo('Build Connection started — sending invites from stored profiles.')
      const final = await pollAutomation(run.id, (row) => setLogs(row.logs || []))
      if (final.status === 'error') {
        setError(final.error || 'Automation failed')
        setInfo('')
      } else {
        setInfo(
          `Finished · sent ${final.result?.sent ?? 0}` +
            (final.result?.skipped ? ` · skipped ${final.result.skipped}` : '') +
            (final.result?.failed ? ` · ${final.result.failed} failed` : ''),
        )
      }
      await refresh()
    } catch (err: unknown) {
      setError(String((err as Error).message || err))
    } finally {
      setBusy(false)
      setActiveRunId(null)
    }
  }

  const onActivateBrandEngage = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    setInfo('')
    setLogs([])
    setProfiles([])
    try {
      const run = await api.activateBrandEngage()
      setActiveRunId(run.id)
      setInfo(
        'Brand Engage started — every logged-in session will like, comment, and repost.',
      )
      const final = await pollAutomation(run.id, (row) => setLogs(row.logs || []))
      if (final.status === 'error') {
        setError(final.error || 'Automation failed')
        setInfo('')
      } else {
        setInfo(
          `Finished · engaged ${final.result?.engaged ?? 0}` +
            (final.result?.skipped ? ` · skipped ${final.result.skipped}` : '') +
            (final.result?.failed ? ` · ${final.result.failed} failed` : ''),
        )
      }
      await refresh()
    } catch (err: unknown) {
      setError(String((err as Error).message || err))
    } finally {
      setBusy(false)
      setActiveRunId(null)
    }
  }

  const selectedCompany = companies.find((c) => c.id === sourceId)

  const historyTitle =
    kind === 'build_connection'
      ? 'Build Connection'
      : kind === 'brand_engage'
        ? 'Brand Engage'
        : 'Company People Fetch'

  const emptyMark =
    kind === 'build_connection' ? '02' : kind === 'brand_engage' ? '03' : '01'

  return (
    <>
      <header className="topbar">
        <div>
          <p className="phase">Phase 03 · Automations</p>
          <h1>Automations</h1>
          <p className="lede">
            Type 1 fetches people and full profiles. Type 2 sends connection
            requests to profiles already stored. Type 3 likes, comments, and
            reposts the latest brand posts across every session.
          </p>
        </div>
        <div className="topbar-meta">
          <span>
            {runs.length} {runLabel} run{runs.length === 1 ? '' : 's'}
          </span>
        </div>
      </header>

      <div className="kind-tabs" role="tablist" aria-label="Automation types">
        <button
          type="button"
          role="tab"
          aria-selected={kind === 'company_people_fetch'}
          className={`kind-tab${kind === 'company_people_fetch' ? ' active' : ''}`}
          onClick={() => setKind('company_people_fetch')}
        >
          <span className="kind-tab-step">01</span>
          Company People Fetch
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={kind === 'build_connection'}
          className={`kind-tab${kind === 'build_connection' ? ' active' : ''}`}
          onClick={() => setKind('build_connection')}
        >
          <span className="kind-tab-step">02</span>
          Build Connection
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={kind === 'brand_engage'}
          className={`kind-tab${kind === 'brand_engage' ? ' active' : ''}`}
          onClick={() => setKind('brand_engage')}
        >
          <span className="kind-tab-step">03</span>
          Brand Engage
        </button>
      </div>

      {error && (
        <div className="banner error" role="alert">
          {error}
        </div>
      )}
      {info && !error && (
        <div className="banner ok" role="status">
          {info}
        </div>
      )}

      {kind === 'company_people_fetch' && (
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>
                Activate Company People Fetch{' '}
                <span className="soft-label">Type 1</span>
              </h2>
              <p>
                Discover profile links from a Company Peoples source, then scrape
                name, experience, education, and more.
              </p>
            </div>
          </div>

          <form className="source-form" onSubmit={onActivateFetch}>
            <div className="source-fields auto-fields">
              <label className="field">
                <span>Session</span>
                <select
                  value={sessionName}
                  onChange={(e) => setSessionName(e.target.value)}
                  required
                  disabled={busy}
                >
                  <option value="" disabled>
                    {loggedIn.length
                      ? 'Select logged-in session'
                      : 'No logged-in sessions'}
                  </option>
                  {loggedIn.map((s) => (
                    <option key={s.name} value={s.name}>
                      {s.name} · {s.cookie_count} cookies
                    </option>
                  ))}
                </select>
              </label>

              <label className="field">
                <span>Company</span>
                <select
                  value={sourceId}
                  onChange={(e) => setSourceId(e.target.value)}
                  required
                  disabled={busy}
                >
                  <option value="" disabled>
                    {companies.length
                      ? 'Select Company Peoples source'
                      : 'Add a Company Peoples source first'}
                  </option>
                  {companies.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.company}
                    </option>
                  ))}
                </select>
              </label>

              <label className="field">
                <span>Max connections</span>
                <input
                  type="number"
                  min={1}
                  max={100}
                  value={maxConnections}
                  onChange={(e) =>
                    setMaxConnections(Number(e.target.value) || 1)
                  }
                  disabled={busy}
                  required
                />
              </label>
            </div>

            {selectedCompany && (
              <p className="field-hint">
                Source URL:{' '}
                <a
                  className="inline-link"
                  href={selectedCompany.link}
                  target="_blank"
                  rel="noreferrer"
                >
                  {selectedCompany.link.replace('https://www.linkedin.com', '')}
                </a>
              </p>
            )}

            <div className="source-form-actions">
              <button
                type="submit"
                className="btn primary"
                disabled={
                  busy || !sessionName || !sourceId || loggedIn.length === 0
                }
              >
                {busy ? 'Running…' : 'Activate'}
              </button>
            </div>
          </form>
        </section>
      )}

      {kind === 'build_connection' && (
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>
                Activate Build Connection{' '}
                <span className="soft-label">Type 2</span>
              </h2>
              <p>
                Picks stored profiles that have not been invited yet and sends
                LinkedIn connection requests (no note).
              </p>
            </div>
          </div>

          <form className="source-form" onSubmit={onActivateConnect}>
            <div className="source-defaults">
              <div className="default-chip">
                <span>Eligible profiles</span>
                <strong>{pendingCount}</strong>
              </div>
              <div className="default-chip">
                <span>Action</span>
                <strong>Send Connect</strong>
              </div>
            </div>

            <div className="source-fields auto-fields-2">
              <label className="field">
                <span>Session</span>
                <select
                  value={sessionName}
                  onChange={(e) => setSessionName(e.target.value)}
                  required
                  disabled={busy}
                >
                  <option value="" disabled>
                    {loggedIn.length
                      ? 'Select logged-in session'
                      : 'No logged-in sessions'}
                  </option>
                  {loggedIn.map((s) => (
                    <option key={s.name} value={s.name}>
                      {s.name} · {s.cookie_count} cookies
                    </option>
                  ))}
                </select>
              </label>

              <label className="field">
                <span>Max request</span>
                <input
                  type="number"
                  min={1}
                  max={50}
                  value={maxRequests}
                  onChange={(e) => setMaxRequests(Number(e.target.value) || 1)}
                  disabled={busy}
                  required
                />
              </label>
            </div>

            <div className="source-form-actions">
              <button
                type="submit"
                className="btn primary"
                disabled={busy || !sessionName || loggedIn.length === 0}
              >
                {busy ? 'Running…' : 'Activate'}
              </button>
            </div>
          </form>
        </section>
      )}

      {kind === 'brand_engage' && (
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>
                Activate Brand Engage{' '}
                <span className="soft-label">Type 3</span>
              </h2>
              <p>
                For every logged-in session: like, comment “Insightful”, and
                repost the latest post from each brand source. Already-engaged
                posts are skipped.
              </p>
            </div>
          </div>

          <form className="source-form" onSubmit={onActivateBrandEngage}>
            <div className="source-defaults">
              <div className="default-chip">
                <span>Sessions</span>
                <strong>{loggedIn.length}</strong>
              </div>
              <div className="default-chip">
                <span>Sources</span>
                <strong>{BRAND_SOURCES.length}</strong>
              </div>
              <div className="default-chip">
                <span>Actions</span>
                <strong>Like · Comment · Repost</strong>
              </div>
            </div>

            <ul className="field-hint" style={{ listStyle: 'none', padding: 0 }}>
              {BRAND_SOURCES.map((url) => (
                <li key={url}>
                  <a
                    className="inline-link"
                    href={url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {url.replace('https://www.linkedin.com', '')}
                  </a>
                </li>
              ))}
            </ul>

            <div className="source-form-actions">
              <button
                type="submit"
                className="btn primary"
                disabled={busy || loggedIn.length === 0}
              >
                {busy ? 'Running…' : 'Activate'}
              </button>
            </div>
          </form>
        </section>
      )}

      {(logs.length > 0 || activeRunId) && (
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>Run activity</h2>
              <p>Live progress from the browser job.</p>
            </div>
          </div>
          <pre className="log">{logs.join('\n') || 'Starting…'}</pre>
        </section>
      )}

      {kind === 'company_people_fetch' && profiles.length > 0 && (
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>Fetched profiles</h2>
              <p>Stored from the latest completed fetch run.</p>
            </div>
            <span className="count-badge">{profiles.length}</span>
          </div>
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Title</th>
                  <th>Company</th>
                  <th>Experience</th>
                  <th>Education</th>
                  <th>Profile</th>
                </tr>
              </thead>
              <tbody>
                {profiles.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <strong>{p.name || '—'}</strong>
                    </td>
                    <td>{p.current_job_title || '—'}</td>
                    <td>{p.current_company || '—'}</td>
                    <td>{p.experiences?.length ?? 0}</td>
                    <td>{p.educations?.length ?? 0}</td>
                    <td className="link-cell">
                      <a href={p.linkedin_url} target="_blank" rel="noreferrer">
                        Open
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Recent runs</h2>
            <p>History of {historyTitle} activations.</p>
          </div>
          <span className="count-badge">{runs.length}</span>
        </div>
        {runs.length === 0 ? (
          <div className="empty">
            <div className="empty-mark">{emptyMark}</div>
            <p>No automation runs yet</p>
            <span>Activate above to start a run.</span>
          </div>
        ) : (
          <ul className="session-list">
            {runs.slice(0, 8).map((r, i) => (
              <li
                key={r.id}
                className="session-row"
                style={{ animationDelay: `${i * 30}ms` }}
              >
                <div className="avatar" data-ready={r.status === 'done'}>
                  {(r.company || r.kind_label || 'AU').slice(0, 2).toUpperCase()}
                </div>
                <div className="session-body">
                  <div className="session-title">
                    {r.kind === 'build_connection'
                      ? `Build Connection · max ${r.max_requests ?? r.max_connections}`
                      : r.kind === 'brand_engage'
                        ? `Brand Engage · ${r.result?.sessions ?? 'all'} sessions`
                        : `${r.company} · max ${r.max_connections}`}
                  </div>
                  <div className="session-meta">
                    <span
                      className={`status ${
                        r.status === 'done' ? 'ready' : 'pending'
                      }`}
                    >
                      <i />
                      {r.status}
                      {r.kind === 'build_connection' && r.result?.sent != null
                        ? ` · ${r.result.sent} sent`
                        : r.kind === 'brand_engage' && r.result?.engaged != null
                          ? ` · ${r.result.engaged} engaged`
                          : r.result?.scraped != null
                            ? ` · ${r.result.scraped} scraped`
                            : ''}
                    </span>
                    <span className="when">
                      {r.kind === 'brand_engage'
                        ? 'All sessions'
                        : `Session ${r.session_name}`}
                    </span>
                  </div>
                </div>
                <div className="session-actions">
                  <button
                    type="button"
                    className="btn ghost"
                    onClick={() => {
                      setLogs(r.logs || [])
                      void loadProfilesFor(r)
                    }}
                  >
                    View
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  )
}
