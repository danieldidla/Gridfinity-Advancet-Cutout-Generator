import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import type { ProjectSummary } from '../lib/types'
import { Banner, Spinner } from '../components/ui'

export default function Projects() {
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const reload = async () => {
    try { setProjects(await api.listProjects()) }
    catch (e) { setError(e instanceof Error ? e.message : 'Projekte konnten nicht geladen werden') }
  }

  useEffect(() => { void reload() }, [])

  const create = async () => {
    setBusy(true)
    try {
      const project = await api.createProject('Neues Projekt')
      navigate(`/p/${project.id}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Projekt konnte nicht angelegt werden')
    } finally { setBusy(false) }
  }

  return (
    <div className="mx-auto max-w-5xl p-4 sm:p-6">
      <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink-50">Projekte</h1>
          <p className="text-sm text-ink-400">
            Angemeldet als {user?.display_name || user?.email}
          </p>
        </div>
        <div className="flex gap-2">
          {user?.is_admin && <Link to="/admin" className="btn-ghost">Verwaltung</Link>}
          <button type="button" className="btn-ghost" onClick={() => { void logout() }}>Abmelden</button>
          <button type="button" className="btn-primary" onClick={create} disabled={busy}>
            Neues Projekt
          </button>
        </div>
      </header>

      {error && <div className="mb-4"><Banner kind="error" onDismiss={() => setError(null)}>{error}</Banner></div>}

      {projects === null ? (
        <Spinner label="Wird geladen…" />
      ) : projects.length === 0 ? (
        <div className="card p-8 text-center">
          <p className="text-ink-300">Noch keine Projekte.</p>
          <button type="button" className="btn-primary mt-4" onClick={create}>
            Erstes Projekt anlegen
          </button>
        </div>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((project) => (
            <li key={project.id} className="card group overflow-hidden">
              <Link to={`/p/${project.id}`} className="block">
                <div className="flex aspect-[4/3] items-center justify-center bg-ink-950/70">
                  {project.thumbnail
                    ? <img src={project.thumbnail} alt="" className="h-full w-full object-contain" />
                    : <span className="text-4xl opacity-20">▦</span>}
                </div>
                <div className="p-3">
                  <h2 className="truncate text-sm font-medium text-ink-100">{project.name}</h2>
                  <p className="text-[11px] text-ink-500">
                    Stand {new Date(project.updated_at).toLocaleString('de-DE')}
                  </p>
                </div>
              </Link>
              <div className="flex gap-1 border-t border-ink-800 p-2 opacity-0
                              transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                <button type="button" className="btn-ghost btn-sm flex-1"
                        onClick={async () => {
                          const copy = await api.duplicateProject(project.id)
                          navigate(`/p/${copy.id}`)
                        }}>Duplizieren</button>
                <button type="button" className="btn-danger btn-sm flex-1"
                        onClick={async () => {
                          if (!confirm(`Projekt „${project.name}“ endgültig löschen?`)) return
                          await api.deleteProject(project.id)
                          void reload()
                        }}>Löschen</button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
