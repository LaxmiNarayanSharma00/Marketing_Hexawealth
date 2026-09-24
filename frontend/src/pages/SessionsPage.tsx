import { FormEvent, useEffect, useState } from 'react'
import { api, pollLogin, type Session } from '../api'

function initials(name: string) {
  const parts = name.replace(/[-_]/g, ' ').trim().split(/\s+/).filter(Boolean)
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
  return name.slice(0, 2).toUpperCase()
}

function formatWhen(iso?: string) {
  if (!iso) return null
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return null
  }
}

type Props = {
  onStats?: (ready: number, total: number) => void
}

export default function SessionsPage({ onStats }: Props) {
  const [sessions, setSessions] = useState<Session[]>([])
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [busyName, setBusyName] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const [logs, setLogs] = useState<string[]>([])

  const refresh = async () => {
    const data = await api.listSessions()
    setSessions(data.sessions)
    const ready = data.sessions.filter((s) => s.has_storage_state).length
    onStats?.(ready, data.sessions.length)
  }

  useEffect(() => {
    refresh().catch((e) => setError(String(e.message || e)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const onCreate = async (e: FormEvent) => {
    e.preventDefault()
    const n = name.trim()
    if (!n) return
    setBusy(true)
    setError('')
    setInfo('')
    try {
      await api.createSession(n)
      setName('')
      setInfo(`Created “${n}”. Open Login to capture the LinkedIn session.`)
      await refresh()
    } catch (err: unknown) {
      setError(String((err as Error).message || err))
    } finally {
      setBusy(false)
    }
  }

  const onLogin = async (s: Session) => {
    setBusy(true)
    setBusyName(s.name)
    setError('')
    setLogs([])
    setInfo(`Browser opening for “${s.name}” — finish LinkedIn login there.`)
    try {
      await api.startLogin(s.name)
      const final = await pollLogin(s.name, (st) => setLogs(st.logs || []))
      if (final.status === 'error') {
        setError(final.error || 'Login failed')
        setInfo('')
      } else {
        setInfo(
          `Session “${s.name}” saved · ${final.session?.cookie_count ?? 0} cookies ready for automation.`,
        )
      }
      await refresh()
    } catch (err: unknown) {
      setError(String((err as Error).message || err))
    } finally {
      setBusy(false)
      setBusyName(null)
    }
  }

  const onDelete = async (s: Session) => {
    if (!confirm(`Delete session “${s.name}”? This cannot be undone.`)) return
    setError('')
    try {
      await api.deleteSession(s.name)
      setInfo(`Removed “${s.name}”.`)
      await refresh()
    } catch (err: unknown) {
      setError(String((err as Error).message || err))
    }
  }

  const readyCount = sessions.filter((s) => s.has_storage_state).length

  return (
    <>
      <header className="topbar">
        <div>
          <p className="phase">Phase 01 · Authentication</p>
          <h1>LinkedIn sessions</h1>
          <p className="lede">
            Sign in once in a real browser. We store the session cookies so later
            stages can act as this account.
          </p>
        </div>
        <div className="topbar-meta">
          <div className="pulse-dot" data-live={readyCount > 0} />
          <span>
            {readyCount > 0
              ? `${readyCount} account${readyCount === 1 ? '' : 's'} authenticated`
              : 'No authenticated accounts yet'}
          </span>
        </div>
      </header>

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

      <section className="panel create-panel">
        <div className="panel-head">
          <div>
            <h2>Register an account</h2>
            <p>Use a short internal label. You will log in after creating it.</p>
          </div>
        </div>
        <form className="create-form" onSubmit={onCreate}>
          <label className="field">
            <span>Session name</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. li-primary"
              autoComplete="off"
              required
            />
          </label>
          <button
            type="submit"
            className="btn primary"
            disabled={busy || !name.trim()}
          >
            Create session
          </button>
        </form>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Saved sessions</h2>
            <p>Authenticated accounts available for future automation stages.</p>
          </div>
          <span className="count-badge">{sessions.length}</span>
        </div>

        {sessions.length === 0 ? (
          <div className="empty">
            <div className="empty-mark">in</div>
            <p>No sessions yet</p>
            <span>Create one above, then click Login to capture cookies.</span>
          </div>
        ) : (
          <ul className="session-list">
            {sessions.map((s, i) => {
              const logging = busyName === s.name
              const when = formatWhen(s.updated_at)
              return (
                <li
                  key={s.name}
                  className={`session-row${logging ? ' is-busy' : ''}`}
                  style={{ animationDelay: `${i * 40}ms` }}
                >
                  <div className="avatar" data-ready={s.has_storage_state}>
                    {initials(s.name)}
                  </div>
                  <div className="session-body">
                    <div className="session-title">{s.name}</div>
                    <div className="session-meta">
                      <span
                        className={`status ${s.has_storage_state ? 'ready' : 'pending'}`}
                      >
                        <i />
                        {logging
                          ? 'Waiting for login…'
                          : s.has_storage_state
                            ? `Logged in · ${s.cookie_count} cookies`
                            : 'Awaiting login'}
                      </span>
                      {when && <span className="when">Updated {when}</span>}
                    </div>
                  </div>
                  <div className="session-actions">
                    <button
                      type="button"
                      className="btn primary"
                      disabled={busy}
                      onClick={() => onLogin(s)}
                    >
                      {logging
                        ? 'Waiting…'
                        : s.has_storage_state
                          ? 'Re-login'
                          : 'Login'}
                    </button>
                    <button
                      type="button"
                      className="btn ghost"
                      disabled={busy}
                      onClick={() => onDelete(s)}
                    >
                      Delete
                    </button>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      {logs.length > 0 && (
        <section className="panel log-panel">
          <div className="panel-head">
            <div>
              <h2>Login activity</h2>
              <p>Live feedback from the browser session.</p>
            </div>
          </div>
          <pre className="log">{logs.join('\n')}</pre>
        </section>
      )}
    </>
  )
}
