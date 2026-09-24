import { FormEvent, useEffect, useState } from 'react'
import {
  api,
  pollAutomation,
  type Audience,
  type AutomationRun,
  type BrandSource,
  type Profile,
  type Schedule,
  type Session,
  type Source,
} from '../api'

type Kind = 'company_people_fetch' | 'build_connection' | 'brand_engage'
type Mode = 'manual' | 'schedule'

const ALL_ENGAGE_ACTIONS = ['like', 'comment', 'repost'] as const

type Props = {
  onCount?: (n: number) => void
}

export default function AutomationsPage({ onCount }: Props) {
  const [kind, setKind] = useState<Kind>('company_people_fetch')
  const [fetchMode, setFetchMode] = useState<Mode>('manual')
  const [connectMode, setConnectMode] = useState<Mode>('manual')
  const [engageMode, setEngageMode] = useState<Mode>('manual')
  const [sessions, setSessions] = useState<Session[]>([])
  const [companies, setCompanies] = useState<Source[]>([])
  const [audiences, setAudiences] = useState<Audience[]>([])
  const [brandSources, setBrandSources] = useState<BrandSource[]>([])
  const [runs, setRuns] = useState<AutomationRun[]>([])
  const [schedules, setSchedules] = useState<Schedule[]>([])
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [pendingCount, setPendingCount] = useState(0)

  const [sessionName, setSessionName] = useState('')
  const [sourceId, setSourceId] = useState('')
  const [audienceSourceId, setAudienceSourceId] = useState('')
  const [maxConnections, setMaxConnections] = useState(10)
  const [maxRequests, setMaxRequests] = useState(10)

  const [engageSourceIds, setEngageSourceIds] = useState<string[]>([])
  const [engageActions, setEngageActions] = useState<string[]>([
    ...ALL_ENGAGE_ACTIONS,
  ])

  const [mapSession, setMapSession] = useState('')
  const [mapSourceId, setMapSourceId] = useState('')
  const [mapMax, setMapMax] = useState(10)
  const [mapTime, setMapTime] = useState('09:00')
  const [mapEngageSourceIds, setMapEngageSourceIds] = useState<string[]>([])
  const [mapEngageActions, setMapEngageActions] = useState<string[]>([
    ...ALL_ENGAGE_ACTIONS,
  ])
  const [showMapDialog, setShowMapDialog] = useState(false)
  const [mapKind, setMapKind] = useState<Kind>('company_people_fetch')
  const [scheduleBusy, setScheduleBusy] = useState(false)

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
    const scheduleKind =
      active === 'build_connection'
        ? 'build_connection'
        : active === 'brand_engage'
          ? 'brand_engage'
          : 'company_people_fetch'
    const [s, c, r, allProfiles, sched, aud, brand] = await Promise.all([
      api.listSessions(),
      api.listSources('company_peoples'),
      api.listAutomations(active),
      api.listProfiles(),
      api.listSchedules(scheduleKind),
      api.listAudiences(),
      api.listBrandSources(),
    ])
    setSessions(s.sessions)
    setCompanies(c.sources)
    setRuns(r.runs)
    setSchedules(sched.schedules.filter((x) => x.kind === scheduleKind))
    setAudiences(aud.audiences)
    setBrandSources(brand.sources)
    if (!engageSourceIds.length && brand.sources.length) {
      setEngageSourceIds(brand.sources.map((x) => x.id))
    }
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
    if (!audienceSourceId) {
      const withEligible = aud.audiences.find((a) => a.eligible > 0 && a.source_id)
      const first = withEligible || aud.audiences.find((a) => a.source_id)
      if (first?.source_id) setAudienceSourceId(first.source_id)
      else if (c.sources[0]) setAudienceSourceId(c.sources[0].id)
    }
    if (!mapSession) {
      const first = s.sessions.find((x) => x.has_storage_state)
      if (first) setMapSession(first.name)
    }
    if (!mapSourceId && c.sources[0]) setMapSourceId(c.sources[0].id)
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

  const openMapDialog = (forKind: Kind) => {
    setMapKind(forKind)
    setMapSession(sessionName || loggedIn[0]?.name || '')
    if (forKind === 'build_connection') {
      setMapSourceId(
        audienceSourceId ||
          audiences.find((a) => a.source_id)?.source_id ||
          companies[0]?.id ||
          '',
      )
      setMapTime('10:00')
    } else if (forKind === 'brand_engage') {
      setMapEngageSourceIds(
        engageSourceIds.length
          ? [...engageSourceIds]
          : brandSources.map((s) => s.id),
      )
      setMapEngageActions(
        engageActions.length ? [...engageActions] : [...ALL_ENGAGE_ACTIONS],
      )
      setMapTime('11:00')
    } else {
      setMapSourceId(sourceId || companies[0]?.id || '')
      setMapTime('09:00')
    }
    setMapMax(10)
    setShowMapDialog(true)
    setError('')
  }

  const onCreateMapping = async (e: FormEvent) => {
    e.preventDefault()
    setScheduleBusy(true)
    setError('')
    try {
      if (mapKind === 'brand_engage') {
        if (!mapSession) {
          throw new Error('Select a session')
        }
        if (!mapEngageSourceIds.length) {
          throw new Error('Select at least one audience (or Select all)')
        }
        if (!mapEngageActions.length) {
          throw new Error('Select at least one action')
        }
        await api.createBrandEngageSchedule({
          session_name: mapSession,
          source_ids: mapEngageSourceIds,
          actions: mapEngageActions,
          run_time: mapTime,
          enabled: true,
        })
      } else if (mapKind === 'build_connection') {
        if (!mapSession || !mapSourceId) return
        await api.createBuildConnectionSchedule({
          session_name: mapSession,
          source_id: mapSourceId,
          max_profiles: mapMax,
          run_time: mapTime,
          enabled: true,
        })
      } else {
        if (!mapSession || !mapSourceId) return
        await api.createCompanyPeopleSchedule({
          session_name: mapSession,
          source_id: mapSourceId,
          max_profiles: mapMax,
          run_time: mapTime,
          enabled: true,
        })
      }
      setShowMapDialog(false)
      setInfo('Schedule mapping added.')
      await refresh()
    } catch (err: unknown) {
      setError(String((err as Error).message || err))
    } finally {
      setScheduleBusy(false)
    }
  }

  const toggleId = (
    list: string[],
    id: string,
    onChange: (next: string[]) => void,
  ) => {
    onChange(
      list.includes(id) ? list.filter((x) => x !== id) : [...list, id],
    )
  }

  const onToggleSchedule = async (row: Schedule) => {
    setScheduleBusy(true)
    setError('')
    try {
      if (row.enabled) {
        await api.pauseSchedule(row.id)
        setInfo(`Paused · ${row.company || 'mapping'}`)
      } else {
        await api.startSchedule(row.id)
        setInfo(`Started · ${row.company || 'mapping'}`)
      }
      await refresh()
    } catch (err: unknown) {
      setError(String((err as Error).message || err))
    } finally {
      setScheduleBusy(false)
    }
  }

  const onDeleteSchedule = async (row: Schedule) => {
    if (!window.confirm(`Remove schedule for ${row.company}?`)) return
    setScheduleBusy(true)
    setError('')
    try {
      await api.deleteSchedule(row.id)
      setInfo('Schedule mapping removed.')
      await refresh()
    } catch (err: unknown) {
      setError(String((err as Error).message || err))
    } finally {
      setScheduleBusy(false)
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
    if (!sessionName || !audienceSourceId) return
    setBusy(true)
    setError('')
    setInfo('')
    setLogs([])
    setProfiles([])
    try {
      const run = await api.activateBuildConnection({
        session_name: sessionName,
        source_id: audienceSourceId,
        max_requests: maxRequests,
      })
      setActiveRunId(run.id)
      setInfo(
        `Build Connection started for ${run.company || 'audience'} — sending invites.`,
      )
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
    if (!sessionName) {
      setError('Select a session')
      return
    }
    if (!engageSourceIds.length) {
      setError('Select at least one audience (or Select all)')
      return
    }
    if (!engageActions.length) {
      setError('Select at least one action')
      return
    }
    setBusy(true)
    setError('')
    setInfo('')
    setLogs([])
    setProfiles([])
    try {
      const run = await api.activateBrandEngage({
        session_name: sessionName,
        source_ids: engageSourceIds,
        actions: engageActions,
      })
      setActiveRunId(run.id)
      setInfo(
        `Brand Engage started · session ${sessionName} · ${engageSourceIds.length} audience(s) · ${engageActions.join(', ')}.`,
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
  const mapCompany = companies.find((c) => c.id === mapSourceId)
  const selectedAudience = audiences.find((a) => a.source_id === audienceSourceId)
  const audienceEligible =
    selectedAudience?.eligible ??
    (audienceSourceId ? 0 : pendingCount)

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
        <>
          <div
            className="mode-tabs"
            role="tablist"
            aria-label="Company People Fetch mode"
          >
            <button
              type="button"
              role="tab"
              aria-selected={fetchMode === 'manual'}
              className={`mode-tab${fetchMode === 'manual' ? ' active' : ''}`}
              onClick={() => setFetchMode('manual')}
            >
              Manual
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={fetchMode === 'schedule'}
              className={`mode-tab${fetchMode === 'schedule' ? ' active' : ''}`}
              onClick={() => setFetchMode('schedule')}
            >
              Schedule
              {schedules.length > 0 && (
                <span className="mode-tab-count">{schedules.length}</span>
              )}
            </button>
          </div>

          {fetchMode === 'manual' && (
            <section className="panel">
              <div className="panel-head">
                <div>
                  <h2>
                    Activate Company People Fetch{' '}
                    <span className="soft-label">Type 1</span>
                  </h2>
                  <p>
                    Discover profile links from a Company Peoples source, then
                    scrape name, experience, education, and more.
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
                      {selectedCompany.link.replace(
                        'https://www.linkedin.com',
                        '',
                      )}
                    </a>
                  </p>
                )}

                <div className="source-form-actions">
                  <button
                    type="submit"
                    className="btn primary"
                    disabled={
                      busy ||
                      !sessionName ||
                      !sourceId ||
                      loggedIn.length === 0
                    }
                  >
                    {busy ? 'Running…' : 'Activate'}
                  </button>
                </div>
              </form>
            </section>
          )}

          {fetchMode === 'schedule' && (
            <section className="panel">
              <div className="panel-head">
                <div>
                  <h2>
                    Schedule Company People Fetch{' '}
                    <span className="soft-label">Daily</span>
                  </h2>
                  <p>
                    Map any logged-in session to a Company Peoples source. Each
                    mapping runs once per day at the local time you set — pause
                    anytime.
                  </p>
                </div>
                <button
                  type="button"
                  className="btn primary"
                  onClick={() => openMapDialog('company_people_fetch')}
                  disabled={scheduleBusy || loggedIn.length === 0}
                >
                  + Add mapping
                </button>
              </div>

              {schedules.length === 0 ? (
                <div className="empty">
                  <div className="empty-mark">+</div>
                  <p>No schedule mappings yet</p>
                  <span>
                    Click Add mapping to link a session to a company source.
                  </span>
                </div>
              ) : (
                <ul className="session-list">
                  {schedules.map((row, i) => (
                    <li
                      key={row.id}
                      className="session-row schedule-row"
                      style={{ animationDelay: `${i * 30}ms` }}
                    >
                      <div
                        className="avatar"
                        data-ready={row.enabled}
                        title={row.enabled ? 'Active' : 'Paused'}
                      >
                        {(row.company || 'SC').slice(0, 2).toUpperCase()}
                      </div>
                      <div className="session-body">
                        <div className="session-title">
                          {row.company || 'Company'} · max {row.max_profiles}
                        </div>
                        <div className="session-meta">
                          <span
                            className={`status ${
                              row.enabled ? 'ready' : 'pending'
                            }`}
                          >
                            <i />
                            {row.enabled ? 'running schedule' : 'paused'}
                          </span>
                          <span className="when">
                            Session {row.session_name}
                          </span>
                          <span className="when">Daily at {row.run_time}</span>
                          {row.last_run_status && (
                            <span className="when">
                              Last {row.last_run_status}
                              {row.fired_on_date
                                ? ` · ${row.fired_on_date}`
                                : ''}
                            </span>
                          )}
                        </div>
                        {row.last_error && (
                          <p className="schedule-error">{row.last_error}</p>
                        )}
                      </div>
                      <div className="session-actions">
                        <button
                          type="button"
                          className="btn ghost"
                          disabled={scheduleBusy}
                          onClick={() => void onToggleSchedule(row)}
                        >
                          {row.enabled ? 'Pause' : 'Start'}
                        </button>
                        <button
                          type="button"
                          className="btn ghost danger-text"
                          disabled={scheduleBusy}
                          onClick={() => void onDeleteSchedule(row)}
                        >
                          Remove
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}
        </>
      )}

      {showMapDialog && (
        <div
          className="dialog-backdrop"
          role="presentation"
          onClick={() => !scheduleBusy && setShowMapDialog(false)}
        >
          <div
            className="dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="map-dialog-title"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="panel-head">
              <div>
                <h2 id="map-dialog-title">
                  {mapKind === 'brand_engage'
                    ? 'New brand engage schedule'
                    : mapKind === 'build_connection'
                      ? 'New connect schedule'
                      : 'New schedule mapping'}
                </h2>
                <p>
                  {mapKind === 'brand_engage'
                    ? 'Session → daily time, audiences, and actions.'
                    : mapKind === 'build_connection'
                      ? 'Session → audience, max requests, and daily time.'
                      : 'Session → company source, profile count, and daily time.'}
                </p>
              </div>
            </div>
            <form className="source-form" onSubmit={onCreateMapping}>
              {mapKind === 'brand_engage' ? (
                <>
                  <label className="field">
                    <span>Session</span>
                    <select
                      value={mapSession}
                      onChange={(e) => setMapSession(e.target.value)}
                      required
                      disabled={scheduleBusy}
                    >
                      <option value="" disabled>
                        Select logged-in session
                      </option>
                      {loggedIn.map((s) => (
                        <option key={s.name} value={s.name}>
                          {s.name} · {s.cookie_count} cookies
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    <span>Daily run time (local)</span>
                    <input
                      type="time"
                      value={mapTime}
                      onChange={(e) => setMapTime(e.target.value)}
                      disabled={scheduleBusy}
                      required
                    />
                  </label>

                  <div className="picker-block">
                    <div className="picker-head">
                      <span>Audience</span>
                      <button
                        type="button"
                        className="btn ghost"
                        disabled={scheduleBusy}
                        onClick={() =>
                          setMapEngageSourceIds(brandSources.map((s) => s.id))
                        }
                      >
                        Select all
                      </button>
                    </div>
                    <div className="check-grid">
                      {brandSources.map((s) => (
                        <label key={s.id} className="check-item">
                          <input
                            type="checkbox"
                            checked={mapEngageSourceIds.includes(s.id)}
                            disabled={scheduleBusy}
                            onChange={() =>
                              toggleId(
                                mapEngageSourceIds,
                                s.id,
                                setMapEngageSourceIds,
                              )
                            }
                          />
                          <span>
                            <strong>{s.label}</strong>
                          </span>
                        </label>
                      ))}
                    </div>
                  </div>

                  <div className="picker-block">
                    <div className="picker-head">
                      <span>Actions</span>
                      <button
                        type="button"
                        className="btn ghost"
                        disabled={scheduleBusy}
                        onClick={() =>
                          setMapEngageActions([...ALL_ENGAGE_ACTIONS])
                        }
                      >
                        Select all
                      </button>
                    </div>
                    <div className="check-grid actions-grid">
                      {ALL_ENGAGE_ACTIONS.map((a) => (
                        <label key={a} className="check-item">
                          <input
                            type="checkbox"
                            checked={mapEngageActions.includes(a)}
                            disabled={scheduleBusy}
                            onChange={() =>
                              toggleId(
                                mapEngageActions,
                                a,
                                setMapEngageActions,
                              )
                            }
                          />
                          <span>
                            <strong>
                              {a === 'comment'
                                ? 'Comment (Insightful)'
                                : a[0]!.toUpperCase() + a.slice(1)}
                            </strong>
                          </span>
                        </label>
                      ))}
                    </div>
                  </div>
                </>
              ) : (
                <>
                  <div className="source-fields auto-fields">
                    <label className="field">
                      <span>Session</span>
                      <select
                        value={mapSession}
                        onChange={(e) => setMapSession(e.target.value)}
                        required
                        disabled={scheduleBusy}
                      >
                        <option value="" disabled>
                          Select logged-in session
                        </option>
                        {loggedIn.map((s) => (
                          <option key={s.name} value={s.name}>
                            {s.name} · {s.cookie_count} cookies
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="field">
                      <span>
                        {mapKind === 'build_connection'
                          ? 'Audience'
                          : 'Company'}
                      </span>
                      <select
                        value={mapSourceId}
                        onChange={(e) => setMapSourceId(e.target.value)}
                        required
                        disabled={scheduleBusy}
                      >
                        <option value="" disabled>
                          {mapKind === 'build_connection'
                            ? 'Select audience'
                            : 'Select Company Peoples source'}
                        </option>
                        {mapKind === 'build_connection'
                          ? audiences
                              .filter((a) => a.source_id)
                              .map((a) => (
                                <option key={a.source_id} value={a.source_id}>
                                  {a.company} · {a.eligible} eligible
                                </option>
                              ))
                          : companies.map((c) => (
                              <option key={c.id} value={c.id}>
                                {c.company}
                              </option>
                            ))}
                      </select>
                    </label>
                    <label className="field">
                      <span>
                        {mapKind === 'build_connection'
                          ? 'Requests per run'
                          : 'Profiles per run'}
                      </span>
                      <input
                        type="number"
                        min={1}
                        max={mapKind === 'build_connection' ? 50 : 100}
                        value={mapMax}
                        onChange={(e) =>
                          setMapMax(Number(e.target.value) || 1)
                        }
                        disabled={scheduleBusy}
                        required
                      />
                    </label>
                    <label className="field">
                      <span>Daily run time (local)</span>
                      <input
                        type="time"
                        value={mapTime}
                        onChange={(e) => setMapTime(e.target.value)}
                        disabled={scheduleBusy}
                        required
                      />
                    </label>
                  </div>
                  {mapCompany && (
                    <p className="field-hint">
                      Source URL:{' '}
                      <a
                        className="inline-link"
                        href={mapCompany.link}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {mapCompany.link.replace(
                          'https://www.linkedin.com',
                          '',
                        )}
                      </a>
                    </p>
                  )}
                </>
              )}
              <div className="source-form-actions dialog-actions">
                <button
                  type="button"
                  className="btn ghost"
                  disabled={scheduleBusy}
                  onClick={() => setShowMapDialog(false)}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="btn primary"
                  disabled={
                    scheduleBusy ||
                    (mapKind === 'brand_engage'
                      ? !mapSession ||
                        !mapEngageSourceIds.length ||
                        !mapEngageActions.length ||
                        loggedIn.length === 0
                      : !mapSession || !mapSourceId || loggedIn.length === 0)
                  }
                >
                  {scheduleBusy ? 'Saving…' : 'Save mapping'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {kind === 'build_connection' && (
        <>
          <div
            className="mode-tabs"
            role="tablist"
            aria-label="Build Connection mode"
          >
            <button
              type="button"
              role="tab"
              aria-selected={connectMode === 'manual'}
              className={`mode-tab${connectMode === 'manual' ? ' active' : ''}`}
              onClick={() => setConnectMode('manual')}
            >
              Manual
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={connectMode === 'schedule'}
              className={`mode-tab${connectMode === 'schedule' ? ' active' : ''}`}
              onClick={() => setConnectMode('schedule')}
            >
              Schedule
              {schedules.length > 0 && (
                <span className="mode-tab-count">{schedules.length}</span>
              )}
            </button>
          </div>

          {connectMode === 'manual' && (
            <section className="panel">
              <div className="panel-head">
                <div>
                  <h2>
                    Activate Build Connection{' '}
                    <span className="soft-label">Type 2</span>
                  </h2>
                  <p>
                    Pick an audience (profiles fetched from a Company Peoples
                    source), then send LinkedIn connection requests (no note).
                  </p>
                </div>
              </div>

              <form className="source-form" onSubmit={onActivateConnect}>
                <div className="source-defaults">
                  <div className="default-chip">
                    <span>Eligible in audience</span>
                    <strong>{audienceEligible}</strong>
                  </div>
                  <div className="default-chip">
                    <span>Action</span>
                    <strong>Send Connect</strong>
                  </div>
                </div>

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
                    <span>Audience</span>
                    <select
                      value={audienceSourceId}
                      onChange={(e) => setAudienceSourceId(e.target.value)}
                      required
                      disabled={busy}
                    >
                      <option value="" disabled>
                        {audiences.length
                          ? 'Select audience (who was fetched)'
                          : 'Fetch people first in Type 1'}
                      </option>
                      {audiences
                        .filter((a) => a.source_id)
                        .map((a) => (
                          <option key={a.source_id} value={a.source_id}>
                            {a.company} · {a.eligible} eligible
                            {a.total ? ` / ${a.total} total` : ''}
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
                      onChange={(e) =>
                        setMaxRequests(Number(e.target.value) || 1)
                      }
                      disabled={busy}
                      required
                    />
                  </label>
                </div>

                {selectedAudience?.source_link && (
                  <p className="field-hint">
                    Audience from:{' '}
                    <a
                      className="inline-link"
                      href={selectedAudience.source_link}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {selectedAudience.source_link.replace(
                        'https://www.linkedin.com',
                        '',
                      )}
                    </a>
                  </p>
                )}

                <div className="source-form-actions">
                  <button
                    type="submit"
                    className="btn primary"
                    disabled={
                      busy ||
                      !sessionName ||
                      !audienceSourceId ||
                      loggedIn.length === 0
                    }
                  >
                    {busy ? 'Running…' : 'Activate'}
                  </button>
                </div>
              </form>
            </section>
          )}

          {connectMode === 'schedule' && (
            <section className="panel">
              <div className="panel-head">
                <div>
                  <h2>
                    Schedule Build Connection{' '}
                    <span className="soft-label">Daily</span>
                  </h2>
                  <p>
                    Map a session to an audience (e.g. Google, IIIT Allahabad).
                    Each mapping sends up to N connects once per day — pause
                    anytime.
                  </p>
                </div>
                <button
                  type="button"
                  className="btn primary"
                  onClick={() => openMapDialog('build_connection')}
                  disabled={scheduleBusy || loggedIn.length === 0}
                >
                  + Add mapping
                </button>
              </div>

              {schedules.length === 0 ? (
                <div className="empty">
                  <div className="empty-mark">+</div>
                  <p>No schedule mappings yet</p>
                  <span>
                    Click Add mapping to link a session to an audience.
                  </span>
                </div>
              ) : (
                <ul className="session-list">
                  {schedules.map((row, i) => (
                    <li
                      key={row.id}
                      className="session-row schedule-row"
                      style={{ animationDelay: `${i * 30}ms` }}
                    >
                      <div
                        className="avatar"
                        data-ready={row.enabled}
                        title={row.enabled ? 'Active' : 'Paused'}
                      >
                        {(row.company || 'BC').slice(0, 2).toUpperCase()}
                      </div>
                      <div className="session-body">
                        <div className="session-title">
                          {row.company || 'Audience'} · max {row.max_profiles}
                        </div>
                        <div className="session-meta">
                          <span
                            className={`status ${
                              row.enabled ? 'ready' : 'pending'
                            }`}
                          >
                            <i />
                            {row.enabled ? 'running schedule' : 'paused'}
                          </span>
                          <span className="when">
                            Session {row.session_name}
                          </span>
                          <span className="when">Daily at {row.run_time}</span>
                          {row.last_run_status && (
                            <span className="when">
                              Last {row.last_run_status}
                              {row.fired_on_date
                                ? ` · ${row.fired_on_date}`
                                : ''}
                            </span>
                          )}
                        </div>
                        {row.last_error && (
                          <p className="schedule-error">{row.last_error}</p>
                        )}
                      </div>
                      <div className="session-actions">
                        <button
                          type="button"
                          className="btn ghost"
                          disabled={scheduleBusy}
                          onClick={() => void onToggleSchedule(row)}
                        >
                          {row.enabled ? 'Pause' : 'Start'}
                        </button>
                        <button
                          type="button"
                          className="btn ghost danger-text"
                          disabled={scheduleBusy}
                          onClick={() => void onDeleteSchedule(row)}
                        >
                          Remove
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}
        </>
      )}

      {kind === 'brand_engage' && (
        <>
          <div
            className="mode-tabs"
            role="tablist"
            aria-label="Brand Engage mode"
          >
            <button
              type="button"
              role="tab"
              aria-selected={engageMode === 'manual'}
              className={`mode-tab${engageMode === 'manual' ? ' active' : ''}`}
              onClick={() => setEngageMode('manual')}
            >
              Manual
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={engageMode === 'schedule'}
              className={`mode-tab${engageMode === 'schedule' ? ' active' : ''}`}
              onClick={() => setEngageMode('schedule')}
            >
              Schedule
              {schedules.length > 0 && (
                <span className="mode-tab-count">{schedules.length}</span>
              )}
            </button>
          </div>

          {engageMode === 'manual' && (
            <section className="panel">
              <div className="panel-head">
                <div>
                  <h2>
                    Activate Brand Engage{' '}
                    <span className="soft-label">Type 3</span>
                  </h2>
                  <p>
                    For the selected session: engage the latest post from
                    selected brand audiences with the actions you choose.
                    Already-engaged posts are skipped.
                  </p>
                </div>
              </div>

              <form className="source-form" onSubmit={onActivateBrandEngage}>
                <div className="source-defaults">
                  <div className="default-chip">
                    <span>Session</span>
                    <strong>{sessionName || '—'}</strong>
                  </div>
                  <div className="default-chip">
                    <span>Audiences</span>
                    <strong>
                      {engageSourceIds.length || 0}/{brandSources.length || 4}
                    </strong>
                  </div>
                  <div className="default-chip">
                    <span>Actions</span>
                    <strong>
                      {engageActions.length
                        ? engageActions
                            .map((a) => a[0]!.toUpperCase() + a.slice(1))
                            .join(' · ')
                        : '—'}
                    </strong>
                  </div>
                </div>

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

                <div className="picker-block">
                  <div className="picker-head">
                    <span>Audience</span>
                    <button
                      type="button"
                      className="btn ghost"
                      disabled={busy}
                      onClick={() =>
                        setEngageSourceIds(brandSources.map((s) => s.id))
                      }
                    >
                      Select all
                    </button>
                  </div>
                  <div className="check-grid">
                    {brandSources.map((s) => (
                      <label key={s.id} className="check-item">
                        <input
                          type="checkbox"
                          checked={engageSourceIds.includes(s.id)}
                          disabled={busy}
                          onChange={() =>
                            toggleId(
                              engageSourceIds,
                              s.id,
                              setEngageSourceIds,
                            )
                          }
                        />
                        <span>
                          <strong>{s.label}</strong>
                          <em>
                            {s.url.replace('https://www.linkedin.com', '')}
                          </em>
                        </span>
                      </label>
                    ))}
                  </div>
                </div>

                <div className="picker-block">
                  <div className="picker-head">
                    <span>Actions</span>
                    <button
                      type="button"
                      className="btn ghost"
                      disabled={busy}
                      onClick={() => setEngageActions([...ALL_ENGAGE_ACTIONS])}
                    >
                      Select all
                    </button>
                  </div>
                  <div className="check-grid actions-grid">
                    {ALL_ENGAGE_ACTIONS.map((a) => (
                      <label key={a} className="check-item">
                        <input
                          type="checkbox"
                          checked={engageActions.includes(a)}
                          disabled={busy}
                          onChange={() =>
                            toggleId(engageActions, a, setEngageActions)
                          }
                        />
                        <span>
                          <strong>
                            {a === 'comment'
                              ? 'Comment (Insightful)'
                              : a[0]!.toUpperCase() + a.slice(1)}
                          </strong>
                        </span>
                      </label>
                    ))}
                  </div>
                </div>

                <div className="source-form-actions">
                  <button
                    type="submit"
                    className="btn primary"
                    disabled={
                      busy ||
                      !sessionName ||
                      loggedIn.length === 0 ||
                      !engageSourceIds.length ||
                      !engageActions.length
                    }
                  >
                    {busy ? 'Running…' : 'Activate'}
                  </button>
                </div>
              </form>
            </section>
          )}

          {engageMode === 'schedule' && (
            <section className="panel">
              <div className="panel-head">
                <div>
                  <h2>
                    Schedule Brand Engage{' '}
                    <span className="soft-label">Daily</span>
                  </h2>
                  <p>
                    Set session, daily time, which brand audiences to engage,
                    and which actions to run.
                  </p>
                </div>
                <button
                  type="button"
                  className="btn primary"
                  onClick={() => openMapDialog('brand_engage')}
                  disabled={scheduleBusy || loggedIn.length === 0}
                >
                  + Add mapping
                </button>
              </div>

              {schedules.length === 0 ? (
                <div className="empty">
                  <div className="empty-mark">+</div>
                  <p>No schedule mappings yet</p>
                  <span>
                    Click Add mapping to set time, audiences, and actions.
                  </span>
                </div>
              ) : (
                <ul className="session-list">
                  {schedules.map((row, i) => (
                    <li
                      key={row.id}
                      className="session-row schedule-row"
                      style={{ animationDelay: `${i * 30}ms` }}
                    >
                      <div
                        className="avatar"
                        data-ready={row.enabled}
                        title={row.enabled ? 'Active' : 'Paused'}
                      >
                        BE
                      </div>
                      <div className="session-body">
                        <div className="session-title">
                          {(row.source_ids?.length || 0) ===
                          brandSources.length
                            ? 'All audiences'
                            : row.company ||
                              `${row.source_ids?.length || 0} audience(s)`}
                          {' · '}
                          {(row.actions || []).join(' · ') || 'no actions'}
                        </div>
                        <div className="session-meta">
                          <span
                            className={`status ${
                              row.enabled ? 'ready' : 'pending'
                            }`}
                          >
                            <i />
                            {row.enabled ? 'running schedule' : 'paused'}
                          </span>
                          <span className="when">
                            Session {row.session_name}
                          </span>
                          <span className="when">Daily at {row.run_time}</span>
                          {row.last_run_status && (
                            <span className="when">
                              Last {row.last_run_status}
                              {row.fired_on_date
                                ? ` · ${row.fired_on_date}`
                                : ''}
                            </span>
                          )}
                        </div>
                        {row.last_error && (
                          <p className="schedule-error">{row.last_error}</p>
                        )}
                      </div>
                      <div className="session-actions">
                        <button
                          type="button"
                          className="btn ghost"
                          disabled={scheduleBusy}
                          onClick={() => void onToggleSchedule(row)}
                        >
                          {row.enabled ? 'Pause' : 'Start'}
                        </button>
                        <button
                          type="button"
                          className="btn ghost danger-text"
                          disabled={scheduleBusy}
                          onClick={() => void onDeleteSchedule(row)}
                        >
                          Remove
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}
        </>
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
                  <th>Audience</th>
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
                    <td>{p.audience || p.source_company || '—'}</td>
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
                      ? `Build Connection · ${r.company || 'audience'} · max ${r.max_requests ?? r.max_connections}`
                      : r.kind === 'brand_engage'
                        ? `${r.company || 'Brand Engage'} · ${r.result?.sessions ?? 'all'} sessions`
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
                    <span className="when">Session {r.session_name}</span>
                    {r.trigger === 'schedule' && (
                      <span className="when">Scheduled</span>
                    )}
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
