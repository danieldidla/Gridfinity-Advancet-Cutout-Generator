import { useState } from 'react'
import { useAuth } from '../lib/auth'
import { Banner } from '../components/ui'

export default function Login() {
  const { info, login, register } = useAuth()
  const firstRun = info ? !info.has_users : false
  const [mode, setMode] = useState<'login' | 'register'>(firstRun ? 'register' : 'login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const canRegister = info?.allow_registration ?? false

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true); setError(null)
    try {
      if (mode === 'register') await register(email, password, name)
      else await login(email, password)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Anmeldung fehlgeschlagen')
    } finally { setBusy(false) }
  }

  return (
    <div className="flex min-h-full items-center justify-center p-4">
      <div className="card w-full max-w-sm p-6">
        <h1 className="text-lg font-semibold text-ink-50">
          {info?.app_name ?? 'Gridfinity Cutout Generator'}
        </h1>
        <p className="mt-1 text-sm text-ink-400">
          {firstRun
            ? 'Noch kein Konto vorhanden. Das erste Konto wird automatisch Administrator.'
            : mode === 'login' ? 'Bitte anmelden.' : 'Neues Konto anlegen.'}
        </p>

        {error && <div className="mt-4"><Banner kind="error">{error}</Banner></div>}

        <form className="mt-5 space-y-3" onSubmit={submit}>
          {mode === 'register' && (
            <div>
              <label className="label mb-1" htmlFor="name">Anzeigename</label>
              <input id="name" className="field" value={name} autoComplete="name"
                     onChange={(e) => setName(e.target.value)} placeholder="optional" />
            </div>
          )}
          <div>
            <label className="label mb-1" htmlFor="email">E-Mail</label>
            <input id="email" type="email" required className="field" value={email}
                   autoComplete="email" onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div>
            <label className="label mb-1" htmlFor="password">Passwort</label>
            <input id="password" type="password" required minLength={8} className="field"
                   value={password} onChange={(e) => setPassword(e.target.value)}
                   autoComplete={mode === 'register' ? 'new-password' : 'current-password'} />
            {mode === 'register' && (
              <p className="mt-1 text-[11px] text-ink-500">Mindestens 8 Zeichen.</p>
            )}
          </div>
          <button type="submit" className="btn-primary w-full" disabled={busy}>
            {busy ? 'Einen Moment…' : mode === 'login' ? 'Anmelden' : 'Konto anlegen'}
          </button>
        </form>

        {(canRegister || mode === 'register') && !firstRun && (
          <button type="button"
                  className="mt-4 w-full text-center text-xs text-ink-400 hover:text-accent-400"
                  onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(null) }}>
            {mode === 'login' ? 'Noch kein Konto? Registrieren' : 'Schon ein Konto? Anmelden'}
          </button>
        )}
      </div>
    </div>
  )
}
