import { FormEvent, useEffect, useMemo, useState } from 'react'
import { api, type Source } from '../api'

type Kind = 'company_peoples' | 'influencer' | 'individual'

const TYPE_LABEL: Record<string, string> = {
  individual: 'Individual',
  influencer: 'Influencer',
}

const USE_CASE_LABEL: Record<string, string> = {
  increase_network: 'Increase Network',
  increase_visibility: 'Increase Visibility',
  reach_out: 'Reach Out',
}

const KIND_META: Record<
  Kind,
  {
    title: string
    step: string
    lede: string
    typeLabel: string
    useCaseLabel: string
    nameLabel: string
    namePlaceholder: string
    linkLabel: string
    linkPlaceholder: string
    emptyTitle: string
    emptyHint: string
  }
> = {
  company_peoples: {
    title: 'Company Peoples',
    step: 'Type 1',
    lede: 'Paste a LinkedIn people/alumni page URL (company, school, or similar). Automation expands people later.',
    typeLabel: 'Individual',
    useCaseLabel: 'Increase Network',
    nameLabel: 'Company',
    namePlaceholder: 'e.g. Google',
    linkLabel: 'People page link',
    linkPlaceholder:
      'https://www.linkedin.com/company/google/people/ or /school/…/alumni/',
    emptyTitle: 'No Company Peoples sources',
    emptyHint: 'Add a LinkedIn company people or school alumni URL above.',
  },
  influencer: {
    title: 'Influencer',
    step: 'Type 2',
    lede: 'Paste LinkedIn profile URLs. Name is stored in the Company field for the shared source model.',
    typeLabel: 'Influencer',
    useCaseLabel: 'Increase Visibility',
    nameLabel: 'Name',
    namePlaceholder: 'e.g. Satya Nadella',
    linkLabel: 'Profile link',
    linkPlaceholder: 'https://www.linkedin.com/in/username/',
    emptyTitle: 'No Influencer sources',
    emptyHint: 'Add a /in/… profile URL above to get started.',
  },
  individual: {
    title: 'Individual',
    step: 'Type 3',
    lede: 'Paste LinkedIn profile URLs for direct outreach. Name is stored in the Company field.',
    typeLabel: 'Individual',
    useCaseLabel: 'Reach Out',
    nameLabel: 'Name',
    namePlaceholder: 'e.g. Jane Doe',
    linkLabel: 'Profile link',
    linkPlaceholder: 'https://www.linkedin.com/in/username/',
    emptyTitle: 'No Individual sources',
    emptyHint: 'Add a /in/… profile URL above to get started.',
  },
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

function guessName(kind: Kind, url: string) {
  try {
    const path = new URL(
      url.startsWith('http') ? url : `https://${url}`,
    ).pathname
    if (kind === 'company_peoples') {
      const company = path.match(/\/company\/([^/]+)\/people/i)
      if (company) {
        return decodeURIComponent(company[1])
          .replace(/-/g, ' ')
          .replace(/\b\w/g, (c) => c.toUpperCase())
      }
      const school = path.match(/\/school\/([^/]+)\/alumni/i)
      if (school) {
        return decodeURIComponent(school[1])
          .replace(/-/g, ' ')
          .replace(/\b\w/g, (c) => c.toUpperCase())
      }
      return ''
    }
    const m = path.match(/\/in\/([^/]+)/i)
    if (!m) return ''
    return decodeURIComponent(m[1])
      .replace(/-/g, ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase())
  } catch {
    return ''
  }
}

type Props = {
  onCount?: (n: number) => void
}

export default function SourcesPage({ onCount }: Props) {
  const [kind, setKind] = useState<Kind>('company_peoples')
  const [sources, setSources] = useState<Source[]>([])
  const [link, setLink] = useState('')
  const [company, setCompany] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')

  const meta = KIND_META[kind]
  const guessed = useMemo(() => guessName(kind, link), [kind, link])
  const nameValue = company || guessed

  const refresh = async (active: Kind = kind) => {
    const data = await api.listSources(active)
    setSources(data.sources)
    const all = await api.listSources()
    onCount?.(all.sources.length)
  }

  useEffect(() => {
    setLink('')
    setCompany('')
    setError('')
    setInfo('')
    refresh(kind).catch((e) => setError(String(e.message || e)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind])

  useEffect(() => {
    if (!info) return
    const t = window.setTimeout(() => setInfo(''), 3500)
    return () => window.clearTimeout(t)
  }, [info])

  const onCreate = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    setInfo('')
    try {
      let row: Source
      if (kind === 'company_peoples') {
        row = await api.createCompanyPeoplesSource({
          link: link.trim(),
          company: nameValue.trim(),
          type: 'individual',
          use_case: 'increase_network',
        })
      } else if (kind === 'influencer') {
        row = await api.createInfluencerSource({
          link: link.trim(),
          company: nameValue.trim(),
          type: 'influencer',
          use_case: 'increase_visibility',
        })
      } else {
        row = await api.createIndividualSource({
          link: link.trim(),
          company: nameValue.trim(),
          type: 'individual',
          use_case: 'reach_out',
        })
      }
      setLink('')
      setCompany('')
      setInfo(`Added ${meta.title} source for ${row.company}.`)
      await refresh()
    } catch (err: unknown) {
      setError(String((err as Error).message || err))
    } finally {
      setBusy(false)
    }
  }

  const onDelete = async (s: Source) => {
    if (!confirm(`Delete source for “${s.company}”?`)) return
    setError('')
    try {
      await api.deleteSource(s.id)
      setInfo(`Removed ${s.company}.`)
      await refresh()
    } catch (err: unknown) {
      setError(String((err as Error).message || err))
    }
  }

  const nameColumn = kind === 'company_peoples' ? 'Company' : 'Name'

  return (
    <>
      <header className="topbar">
        <div>
          <p className="phase">Phase 02 · Sources</p>
          <h1>Sources</h1>
          <p className="lede">
            Choose a source type below. Each type shares the same model: Type,
            Company (or name), Link, Use case.
          </p>
        </div>
        <div className="topbar-meta">
          <span>
            {sources.length} {meta.title.toLowerCase()}
          </span>
        </div>
      </header>

      <div className="kind-tabs" role="tablist" aria-label="Source types">
        {(
          [
            ['company_peoples', '01', 'Company Peoples'],
            ['influencer', '02', 'Influencer'],
            ['individual', '03', 'Individual'],
          ] as const
        ).map(([id, step, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={kind === id}
            className={`kind-tab${kind === id ? ' active' : ''}`}
            onClick={() => setKind(id)}
          >
            <span className="kind-tab-step">{step}</span>
            {label}
          </button>
        ))}
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

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>
              Add {meta.title}{' '}
              <span className="soft-label">{meta.step}</span>
            </h2>
            <p>{meta.lede}</p>
          </div>
        </div>

        <form className="source-form" onSubmit={onCreate}>
          <div className="source-defaults">
            <div className="default-chip">
              <span>Type</span>
              <strong>{meta.typeLabel}</strong>
            </div>
            <div className="default-chip">
              <span>Use case</span>
              <strong>{meta.useCaseLabel}</strong>
            </div>
            <div className="default-chip">
              <span>Source kind</span>
              <strong>{meta.title}</strong>
            </div>
          </div>

          <div className="source-fields">
            <label className="field field-span-2">
              <span>{meta.linkLabel}</span>
              <input
                value={link}
                onChange={(e) => setLink(e.target.value)}
                placeholder={meta.linkPlaceholder}
                autoComplete="off"
                required
              />
            </label>
            <label className="field">
              <span>{meta.nameLabel}</span>
              <input
                value={company}
                onChange={(e) => setCompany(e.target.value)}
                placeholder={guessed || meta.namePlaceholder}
                autoComplete="off"
              />
            </label>
          </div>

          <div className="source-form-actions">
            <button
              type="submit"
              className="btn primary"
              disabled={busy || !link.trim()}
            >
              {busy ? 'Saving…' : `Add ${meta.title}`}
            </button>
          </div>
        </form>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Saved {meta.title}</h2>
            <p>Sources of this type ready for later automation.</p>
          </div>
          <span className="count-badge">{sources.length}</span>
        </div>

        {sources.length === 0 ? (
          <div className="empty">
            <div className="empty-mark">
              {kind === 'company_peoples' ? '01' : kind === 'influencer' ? '02' : '03'}
            </div>
            <p>{meta.emptyTitle}</p>
            <span>{meta.emptyHint}</span>
          </div>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Type</th>
                  <th>{nameColumn}</th>
                  <th>Link</th>
                  <th>Use case</th>
                  <th>Added</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {sources.map((s) => (
                  <tr key={s.id}>
                    <td>
                      <span className="tag">{TYPE_LABEL[s.type] || s.type}</span>
                    </td>
                    <td>
                      <strong>{s.company}</strong>
                    </td>
                    <td className="link-cell">
                      <a href={s.link} target="_blank" rel="noreferrer">
                        {s.link.replace('https://www.linkedin.com', '')}
                      </a>
                    </td>
                    <td>{USE_CASE_LABEL[s.use_case] || s.use_case}</td>
                    <td className="muted-cell">{formatWhen(s.created_at)}</td>
                    <td className="actions-cell">
                      <button
                        type="button"
                        className="btn ghost"
                        onClick={() => onDelete(s)}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  )
}
