import { useEffect, useId, useRef, useState, type ReactNode } from 'react'

export function Section({ title, children, defaultOpen = true, aside }: {
  title: string; children: ReactNode; defaultOpen?: boolean; aside?: ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className="border-b border-ink-800 last:border-0">
      <div className="flex items-center gap-2 px-3 py-2">
        <button type="button" onClick={() => setOpen(!open)}
                className="panel-title flex-1 text-left hover:text-ink-200">
          <span>{title}</span>
          <span className={`transition-transform ${open ? 'rotate-90' : ''}`}>›</span>
        </button>
        {aside}
      </div>
      {open && <div className="space-y-3 px-3 pb-4">{children}</div>}
    </section>
  )
}

interface NumberFieldProps {
  label: string
  value: number
  onChange: (value: number, final: boolean) => void
  min?: number
  max?: number
  step?: number
  unit?: string
  hint?: string
  disabled?: boolean
}

/**
 * Slider and numeric entry over one value. `final` marks the end of a gesture,
 * which is what the editor uses to decide when to close an undo step.
 */
export function NumberField({
  label, value, onChange, min = 0, max = 100, step = 0.1, unit = 'mm', hint, disabled,
}: NumberFieldProps) {
  const id = useId()
  const [text, setText] = useState(String(value))
  const editing = useRef(false)

  useEffect(() => { if (!editing.current) setText(formatNumber(value)) }, [value])

  const commitText = () => {
    editing.current = false
    const parsed = Number(text.replace(',', '.'))
    if (Number.isFinite(parsed)) {
      onChange(clamp(parsed, min, max), true)
    } else {
      setText(formatNumber(value))
    }
  }

  return (
    <div className={disabled ? 'opacity-45' : undefined}>
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <label htmlFor={id} className="label">{label}</label>
        <div className="flex items-baseline gap-1">
          <input
            id={id}
            className="w-16 rounded border border-ink-700 bg-ink-950/60 px-1.5 py-0.5
                       text-right font-mono text-xs text-ink-100 outline-none
                       focus:border-accent-500"
            value={text}
            disabled={disabled}
            inputMode="decimal"
            onFocus={() => { editing.current = true }}
            onChange={(e) => setText(e.target.value)}
            onBlur={commitText}
            onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur() }}
          />
          {unit && <span className="text-[10px] text-ink-500">{unit}</span>}
        </div>
      </div>
      <input
        type="range"
        min={min} max={max} step={step} value={clamp(value, min, max)}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value), false)}
        onPointerUp={(e) => onChange(Number((e.target as HTMLInputElement).value), true)}
        onKeyUp={(e) => onChange(Number((e.target as HTMLInputElement).value), true)}
      />
      {hint && <p className="mt-1 text-[11px] leading-snug text-ink-500">{hint}</p>}
    </div>
  )
}

export function Toggle({ label, checked, onChange, hint, disabled }: {
  label: string; checked: boolean; onChange: (value: boolean) => void
  hint?: string; disabled?: boolean
}) {
  return (
    <label className={`flex cursor-pointer items-start gap-2.5 ${disabled ? 'opacity-45' : ''}`}>
      <input
        type="checkbox" checked={checked} disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4 shrink-0 accent-accent-500"
      />
      <span className="min-w-0">
        <span className="block text-sm text-ink-100">{label}</span>
        {hint && <span className="block text-[11px] leading-snug text-ink-500">{hint}</span>}
      </span>
    </label>
  )
}

export function SelectField<T extends string>({ label, value, options, onChange, hint }: {
  label: string; value: T; options: { value: T; label: string }[]
  onChange: (value: T) => void; hint?: string
}) {
  const id = useId()
  return (
    <div>
      <label htmlFor={id} className="label mb-1">{label}</label>
      <select id={id} className="field" value={value}
              onChange={(e) => onChange(e.target.value as T)}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      {hint && <p className="mt-1 text-[11px] leading-snug text-ink-500">{hint}</p>}
    </div>
  )
}

export function IntField({ label, value, onChange, min = 1, max = 12 }: {
  label: string; value: number; onChange: (value: number) => void
  min?: number; max?: number
}) {
  return (
    <div>
      <label className="label mb-1">{label}</label>
      <div className="flex items-stretch gap-1">
        <button type="button" className="btn-ghost btn-sm w-8"
                onClick={() => onChange(clamp(value - 1, min, max))}
                disabled={value <= min}>−</button>
        <input
          className="field flex-1 text-center font-mono"
          value={value}
          inputMode="numeric"
          onChange={(e) => {
            const parsed = parseInt(e.target.value, 10)
            if (Number.isFinite(parsed)) onChange(clamp(parsed, min, max))
          }}
        />
        <button type="button" className="btn-ghost btn-sm w-8"
                onClick={() => onChange(clamp(value + 1, min, max))}
                disabled={value >= max}>+</button>
      </div>
    </div>
  )
}

export function Modal({ open, onClose, title, children, wide }: {
  open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = previous
    }
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/70 p-0
                    sm:items-center sm:p-4" role="dialog" aria-modal="true"
         onClick={onClose}>
      <div
        className={`card flex max-h-[94vh] w-full flex-col overflow-hidden rounded-b-none
                    sm:rounded-xl ${wide ? 'sm:max-w-5xl' : 'sm:max-w-xl'}`}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-ink-800 px-4 py-3">
          <h2 className="text-sm font-semibold text-ink-100">{title}</h2>
          <button type="button" onClick={onClose}
                  className="rounded px-2 py-1 text-ink-400 hover:bg-ink-800 hover:text-ink-100"
                  aria-label="Schließen">✕</button>
        </header>
        <div className="scrollbar-thin flex-1 overflow-y-auto p-4">{children}</div>
      </div>
    </div>
  )
}

export function Banner({ kind = 'info', children, onDismiss }: {
  kind?: 'info' | 'warn' | 'error' | 'success'; children: ReactNode; onDismiss?: () => void
}) {
  const styles = {
    info: 'border-ink-700 bg-ink-800/60 text-ink-200',
    warn: 'border-amber-800/70 bg-amber-950/50 text-amber-200',
    error: 'border-red-800/70 bg-red-950/50 text-red-200',
    success: 'border-accent-700 bg-accent-900/40 text-accent-200',
  }[kind]
  return (
    <div className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-xs leading-relaxed ${styles}`}>
      <div className="flex-1">{children}</div>
      {onDismiss && (
        <button type="button" onClick={onDismiss} className="shrink-0 opacity-60 hover:opacity-100"
                aria-label="Ausblenden">✕</button>
      )}
    </div>
  )
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-xs text-ink-400">
      <span className="h-3 w-3 animate-spin rounded-full border-2 border-ink-600 border-t-accent-400" />
      {label}
    </span>
  )
}

export const clamp = (value: number, min: number, max: number) =>
  Math.min(max, Math.max(min, value))

export const formatNumber = (value: number) =>
  Number.isInteger(value) ? String(value) : String(Math.round(value * 1000) / 1000)
