import { FormEvent, useEffect, useRef, useState } from 'react'
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

/** Accept raw Playwright state or { name?, storage_state } export wrapper. */
function parseStoragePayload(raw: string): {
  nameHint?: string
  storageState: unknown
} {
  const parsed = JSON.parse(raw) as Record<string, unknown>
  if (
    parsed &&
    typeof parsed === 'object' &&
    parsed.storage_state &&
    typeof parsed.storage_state === 'object'
  ) {
    return {
      nameHint: typeof parsed.name === 'string' ? parsed.name : undefined,
      storageState: parsed.storage_state,
    }
  }
  return { storageState: parsed }
}

type Props = {
  onStats?: (ready: number, total: number) => void
}

export default function SessionsPage({ onStats }: Props) {
  const [sessions, setSessions] = useState<Session[]>([])
  const [name, setName] = useState('')
  const [importName, setImportName] = useState('')
  const [importJson, setImportJson] = useState('')
  const [busy, setBusy] = useState(false)
  const [busyName, setBusyName] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const [logs, setLogs] = useState<string[]>([])
  const fileRef = useRef<HTMLInputElement>(null)

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
      setInfo(
        `Created “${n}”. Use Login, or Import session cookies below.`,
      )
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

  const onExport = async (s: Session) => {
    setError('')
    setInfo('')
    try {
      const data = await api.exportStorageState(s.name)
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: 'application/json',
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${s.name}-storage-state.json`
      a.click()
      URL.revokeObjectURL(url)
      setInfo(
        `Exported “${s.name}” (${data.cookie_count} cookies). Upload that file on prod via Import.`,
      )
    } catch (err: unknown) {
      setError(String((err as Error).message || err))
    }
  }

  const onImportFile = async (file: File) => {
    const text = await file.text()
    setImportJson(text)
    try {
      const { nameHint } = parseStoragePayload(text)
      if (nameHint && !importName.trim()) setImportName(nameHint)
    } catch {
      /* user can fix JSON in the textarea */
    }
  }

  const onImport = async (e: FormEvent) => {
    e.preventDefault()
    const n = importName.trim()
    if (!n) {
      setError('Enter a session name for the import.')
      return
    }
    if (!importJson.trim()) {
      setError('Paste storage-state JSON or choose an export file.')
      return
    }
    setBusy(true)
    setError('')
    setInfo('')
    try {
      const { storageState } = parseStoragePayload(importJson)
      const saved = await api.importStorageState(n, storageState)
      setImportJson('')
      setImportName('')
      if (fileRef.current) fileRef.current.value = ''
      setInfo(
        `Imported “${saved.name}” · ${saved.cookie_count} cookies. Ready for automation.`,
      )
      await refresh()
    } catch (err: unknown) {
      setError(String((err as Error).message || err))
    } finally {
      setBusy(false)
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
            Sign in once in a real browser, or import cookies captured elsewhere.
            We store the session so later stages can act as this account.
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
            <h2>Import session cookies</h2>
            <p>
              Paste or upload a Playwright storage-state JSON (from Export on
              another machine). Creates the session if it does not exist.
            </p>
          </div>
        </div>
        <form className="import-form" onSubmit={onImport}>
          <label className="field">
            <span>Session name</span>
            <input
              value={importName}
              onChange={(e) => setImportName(e.target.value)}
              placeholder="e.g. li-primary"
              autoComplete="off"
              required
            />
          </label>
          <label className="field">
            <span>Export file</span>
            <input
              ref={fileRef}
              type="file"
              accept="application/json,.json"
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) void onImportFile(f)
              }}
            />
          </label>
          <label className="field field-span-2">
            <span>Storage state JSON</span>
            <textarea
              value={importJson}
              onChange={(e) => setImportJson(e.target.value)}
              placeholder='{"cookies":[{"name":"li_at","value":"…","domain":".linkedin.com","path":"/"}],"origins":[]}'
              rows={6}
              spellCheck={false}
            />
          </label>
          <div className="import-actions">
            <button
              type="submit"
              className="btn primary"
              disabled={busy || !importName.trim() || !importJson.trim()}
            >
              Import cookies
            </button>
            <p className="field-hint">
              Local → prod: Export here after Login, then open this UI on prod and
              Import the same file.
            </p>
          </div>
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
            <span>
              Create one above and Login, or Import cookies from another machine.
            </span>
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
                    {s.has_storage_state && (
                      <button
                        type="button"
                        className="btn"
                        disabled={busy}
                        onClick={() => onExport(s)}
                        title="Download cookies for prod import"
                      >
                        Export
                      </button>
                    )}
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
