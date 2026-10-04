import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import type { User } from '../lib/types'
import { Banner, Spinner } from '../components/ui'

export default function Admin() {
  const { user } = useAuth()
  const [users, setUsers] = useState<User[] | null>(null)
  const [stats, setStats] = useState<Record<string, number> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState({ email: '', password: '', display_name: '' })

  const reload = async () => {
    try {
      setUsers(await api.adminUsers())
      setStats(await api.adminStats())
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Laden fehlgeschlagen')
    }
  }
  useEffect(() => { void reload() }, [])

  const guard = async (action: () => Promise<unknown>) => {
    try { await action(); void reload() }
    catch (e) { setError(e instanceof Error ? e.message : 'Aktion fehlgeschlagen') }
  }

  return (
    <div className="mx-auto max-w-4xl p-4 sm:p-6">
      <header className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-semibold text-ink-50">Verwaltung</h1>
        <Link to="/" className="btn-ghost">Zurück</Link>
      </header>

      {error && <div className="mb-4"><Banner kind="error" onDismiss={() => setError(null)}>{error}</Banner></div>}

      {stats && (
        <div className="card mb-6 grid grid-cols-2 gap-3 p-4 sm:grid-cols-4">
          {Object.entries({
            users: 'Konten', projects: 'Projekte', images: 'Fotos', scans: '3D-Aufnahmen',
            shots: 'Scan-Bilder', jobs_queued: 'Warteschlange', jobs_running: 'in Arbeit',
          }).map(([key, label]) => (
            <div key={key}>
              <div className="font-mono text-lg text-ink-50">{stats[key] ?? 0}</div>
              <div className="text-[11px] uppercase tracking-wide text-ink-500">{label}</div>
            </div>
          ))}
        </div>
      )}

      <section className="card mb-6 p-4">
        <h2 className="panel-title mb-3"><span>Konto anlegen</span></h2>
        <form className="grid gap-2 sm:grid-cols-4"
              onSubmit={(e) => {
                e.preventDefault()
                void guard(async () => {
                  await api.adminCreateUser(form.email, form.password, form.display_name)
                  setForm({ email: '', password: '', display_name: '' })
                })
              }}>
          <input className="field" placeholder="E-Mail" type="email" required value={form.email}
                 onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <input className="field" placeholder="Name" value={form.display_name}
                 onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
          <input className="field" placeholder="Passwort" type="password" required minLength={8}
                 value={form.password}
                 onChange={(e) => setForm({ ...form, password: e.target.value })} />
          <button type="submit" className="btn-primary">Anlegen</button>
        </form>
      </section>

      <section className="card p-4">
        <h2 className="panel-title mb-3"><span>Konten</span></h2>
        {users === null ? <Spinner label="Wird geladen…" /> : (
          <ul className="divide-y divide-ink-800">
            {users.map((entry) => (
              <li key={entry.id} className="flex flex-wrap items-center gap-2 py-2.5">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm text-ink-100">
                    {entry.display_name || entry.email}
                    {entry.is_admin && <span className="ml-2 rounded bg-accent-900/60 px-1.5
                                                        py-0.5 text-[10px] text-accent-300">Admin</span>}
                  </div>
                  <div className="truncate text-[11px] text-ink-500">{entry.email}</div>
                </div>
                <button type="button" className="btn-ghost btn-sm"
                        disabled={entry.id === user?.id}
                        onClick={() => void guard(() =>
                          api.adminUpdateUser(entry.id, { is_admin: !entry.is_admin }))}>
                  {entry.is_admin ? 'Adminrechte entziehen' : 'Zum Admin machen'}
                </button>
                <button type="button" className="btn-ghost btn-sm"
                        onClick={() => {
                          const password = prompt('Neues Passwort (mindestens 8 Zeichen)')
                          if (password) void guard(() => api.adminUpdateUser(entry.id, { password }))
                        }}>Passwort setzen</button>
                <button type="button" className="btn-danger btn-sm"
                        disabled={entry.id === user?.id}
                        onClick={() => {
                          if (confirm(`Konto ${entry.email} mit allen Projekten löschen?`)) {
                            void guard(() => api.adminDeleteUser(entry.id))
                          }
                        }}>Löschen</button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
