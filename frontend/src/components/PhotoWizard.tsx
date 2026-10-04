import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import type { ImageInfo, Point, TraceResult, TraceSettings } from '../lib/types'
import PhotoPool from './PhotoPool'
import TracePanel, { defaultTraceSettings } from './TracePanel'
import { Banner, Modal, NumberField, Spinner } from './ui'

type View = 'pool' | 'corners' | 'trace'

interface Props {
  open: boolean
  projectId: string
  images: ImageInfo[]
  onClose: () => void
  onImagesChanged: (images: ImageInfo[]) => void
  onCreate: (result: TraceResult, image: ImageInfo) => void
}

const PAPERS = [
  { value: 'a4', label: 'DIN A4 (210 × 297 mm)' },
  { value: 'a5', label: 'DIN A5 (148 × 210 mm)' },
  { value: 'a3', label: 'DIN A3 (297 × 420 mm)' },
  { value: 'letter', label: 'US Letter (215,9 × 279,4 mm)' },
] as const

export default function PhotoWizard({
  open, projectId, images, onClose, onImagesChanged, onCreate,
}: Props) {
  const { info } = useAuth()
  const [view, setView] = useState<View>('pool')
  const [image, setImage] = useState<ImageInfo | null>(null)
  const [error, setError] = useState<string | null>(null)

  const close = () => { setView('pool'); setImage(null); setError(null); onClose() }

  const pick = (picked: ImageInfo) => {
    setImage(picked)
    setView(picked.has_rectified ? 'trace' : 'corners')
  }

  const title = view === 'pool' ? 'Fotos'
    : view === 'corners' ? 'Blatt ausrichten'
    : `Objekt freistellen${image?.note ? ` · ${image.note}` : ''}`

  return (
    <Modal open={open} onClose={close} wide title={title}>
      {error && <div className="mb-3"><Banner kind="error" onDismiss={() => setError(null)}>{error}</Banner></div>}

      {view === 'pool' && (
        <PhotoPool
          projectId={projectId} images={images}
          maxUploadMb={info?.max_upload_mb ?? 40}
          onChanged={onImagesChanged} onProcess={pick}
        />
      )}

      {view === 'corners' && image && (
        <CornerStep
          projectId={projectId} image={image}
          onBack={() => setView('pool')}
          onError={setError}
          onDone={(updated) => {
            onImagesChanged(images.map((i) => (i.id === updated.id ? updated : i)))
            setImage(updated); setView('trace')
          }}
        />
      )}

      {view === 'trace' && image && (
        <TraceStep
          projectId={projectId} image={image}
          onBack={() => setView('corners')}
          onPool={() => setView('pool')}
          onError={setError}
          onDone={async (result) => {
            onCreate(result, image)
            try {
              const updated = await api.updateImage(projectId, image.id, { processed: true })
              onImagesChanged(images.map((i) => (i.id === updated.id ? updated : i)))
            } catch { /* the cutout exists either way */ }
            setView('pool')
          }}
        />
      )}
    </Modal>
  )
}

/* ------------------------------------------------------------- corners --- */

function CornerStep({ projectId, image, onBack, onDone, onError }: {
  projectId: string; image: ImageInfo
  onBack: () => void
  onDone: (image: ImageInfo) => void
  onError: (message: string) => void
}) {
  const [corners, setCorners] = useState<Point[]>(
    image.corners ?? defaultCorners(image.width, image.height))
  const [paper, setPaper] = useState<string>(image.paper || 'a4')
  const [busy, setBusy] = useState(false)
  const [dragIndex, setDragIndex] = useState<number | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)

  const toImage = useCallback((event: PointerEvent | React.PointerEvent): Point => {
    const svg = svgRef.current
    if (!svg) return [0, 0]
    const rect = svg.getBoundingClientRect()
    const scale = Math.min(rect.width / image.width, rect.height / image.height)
    const offsetX = (rect.width - image.width * scale) / 2
    const offsetY = (rect.height - image.height * scale) / 2
    return [
      clamp((event.clientX - rect.left - offsetX) / scale, 0, image.width),
      clamp((event.clientY - rect.top - offsetY) / scale, 0, image.height),
    ]
  }, [image.width, image.height])

  useEffect(() => {
    if (dragIndex === null) return
    const move = (event: PointerEvent) => {
      const point = toImage(event)
      setCorners((previous) => previous.map((c, i) => (i === dragIndex ? point : c)))
    }
    const up = () => setDragIndex(null)
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    return () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
  }, [dragIndex, toImage])

  const detect = async () => {
    setBusy(true)
    try {
      const updated = await api.detectSheet(projectId, image.id)
      if (updated.corners) setCorners(updated.corners)
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Automatische Erkennung fehlgeschlagen')
    } finally { setBusy(false) }
  }

  const confirm = async () => {
    setBusy(true)
    try {
      onDone(await api.rectify(projectId, image.id, { corners, paper, px_per_mm: 8 }))
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Entzerren fehlgeschlagen')
    } finally { setBusy(false) }
  }

  const radius = Math.max(image.width, image.height) / 90

  return (
    <div className="space-y-3">
      <p className="text-sm text-ink-300">
        Zieh die vier Punkte genau auf die Ecken des Blattes. Je genauer, desto
        genauer das Maß.
      </p>

      <div className="overflow-hidden rounded-lg border border-ink-700 bg-black">
        <svg ref={svgRef} viewBox={`0 0 ${image.width} ${image.height}`}
             preserveAspectRatio="xMidYMid meet" className="max-h-[52vh] w-full touch-none">
          <image href={api.imageUrl(projectId, image.id)} x={0} y={0}
                 width={image.width} height={image.height} />
          <polygon points={corners.map((c) => c.join(',')).join(' ')}
                   className="fill-accent-500/15 stroke-accent-400"
                   strokeWidth={Math.max(2, radius / 3)} />
          {corners.map((corner, index) => (
            <g key={index}>
              <circle cx={corner[0]} cy={corner[1]} r={radius}
                      className="fill-accent-400/90 stroke-ink-950" strokeWidth={radius / 5}
                      style={{ cursor: 'grab' }}
                      onPointerDown={(e) => { e.preventDefault(); setDragIndex(index) }} />
              <text x={corner[0]} y={corner[1] - radius * 1.6} textAnchor="middle"
                    className="fill-accent-200" fontSize={radius * 1.7}>
                {['OL', 'OR', 'UR', 'UL'][index]}
              </text>
            </g>
          ))}
        </svg>
      </div>

      <div>
        <label className="label mb-1">Referenzblatt</label>
        <select className="field" value={paper} onChange={(e) => setPaper(e.target.value)}>
          {PAPERS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
        </select>
      </div>

      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn-ghost" onClick={onBack}>Zu den Fotos</button>
        <button type="button" className="btn-ghost" onClick={detect} disabled={busy}>
          Automatisch erkennen
        </button>
        <button type="button" className="btn-primary flex-1" onClick={confirm} disabled={busy}>
          {busy ? 'Wird entzerrt…' : 'Entzerren und weiter'}
        </button>
      </div>
    </div>
  )
}

/* --------------------------------------------------------------- trace --- */

interface StrokeDraft { points: [number, number][]; foreground: boolean }

function TraceStep({ projectId, image, onBack, onPool, onDone, onError }: {
  projectId: string; image: ImageInfo
  onBack: () => void
  onPool: () => void
  onDone: (result: TraceResult) => void
  onError: (message: string) => void
}) {
  const { info } = useAuth()
  const widthMm = image.trace?.width_mm ?? 210
  const heightMm = image.trace?.height_mm ?? 297
  const pxWidth = Math.round(widthMm * image.px_per_mm)
  const pxHeight = Math.round(heightMm * image.px_per_mm)

  const [settings, setSettings] = useState<TraceSettings>(
    () => ({ ...defaultTraceSettings(), ...(image.settings ?? {}) }))
  const [rect, setRect] = useState<[number, number, number, number] | null>(null)
  const [strokes, setStrokes] = useState<StrokeDraft[]>([])
  const [mode, setMode] = useState<'rect' | 'keep' | 'drop'>('keep')
  const [result, setResult] = useState<TraceResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [showMask, setShowMask] = useState(true)

  const svgRef = useRef<SVGSVGElement>(null)
  const drawing = useRef<{ kind: 'rect' | 'stroke'; start: [number, number] } | null>(null)

  const toPixels = useCallback((event: PointerEvent | React.PointerEvent): [number, number] => {
    const svg = svgRef.current
    if (!svg) return [0, 0]
    const box = svg.getBoundingClientRect()
    const scale = Math.min(box.width / pxWidth, box.height / pxHeight)
    const offsetX = (box.width - pxWidth * scale) / 2
    const offsetY = (box.height - pxHeight * scale) / 2
    return [
      Math.round(clamp((event.clientX - box.left - offsetX) / scale, 0, pxWidth)),
      Math.round(clamp((event.clientY - box.top - offsetY) / scale, 0, pxHeight)),
    ]
  }, [pxWidth, pxHeight])

  const run = useCallback(async (override?: Partial<TraceSettings>) => {
    setBusy(true)
    try {
      const body = {
        ...settings, ...override, rect,
        strokes: strokes.map((s) => ({ points: s.points, foreground: s.foreground })),
      }
      setResult(await api.trace(projectId, image.id, body))
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Freistellen fehlgeschlagen')
    } finally { setBusy(false) }
  }, [projectId, image.id, settings, rect, strokes, onError])

  // A first pass as soon as the photo opens: with the hybrid engine it is
  // usually right straight away, and seeing that is faster than reading about it.
  const started = useRef(false)
  useEffect(() => {
    if (started.current) return
    started.current = true
    void run()
  }, [run])

  useEffect(() => {
    const move = (event: PointerEvent) => {
      if (!drawing.current) return
      const point = toPixels(event)
      if (drawing.current.kind === 'rect') {
        const [sx, sy] = drawing.current.start
        setRect([Math.min(sx, point[0]), Math.min(sy, point[1]),
                 Math.abs(point[0] - sx), Math.abs(point[1] - sy)])
      } else {
        setStrokes((previous) => {
          const copy = [...previous]
          const last = copy[copy.length - 1]
          copy[copy.length - 1] = { ...last, points: [...last.points, point] }
          return copy
        })
      }
    }
    const up = () => { drawing.current = null }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    return () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
  }, [toPixels])

  const start = (event: React.PointerEvent) => {
    event.preventDefault()
    const point = toPixels(event)
    if (mode === 'rect') {
      drawing.current = { kind: 'rect', start: point }
      setRect([point[0], point[1], 0, 0])
    } else {
      drawing.current = { kind: 'stroke', start: point }
      setStrokes((previous) => [...previous, { points: [point], foreground: mode === 'keep' }])
    }
  }

  const patch = (changes: Partial<TraceSettings>) =>
    setSettings((previous) => ({ ...previous, ...changes }))

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr,320px]">
      <div className="space-y-3">
        <p className="text-sm text-ink-300">
          Meistens stimmt die Kontur sofort. Wenn nicht: mit <strong>Behalten</strong> über
          fehlende Stellen malen, mit <strong>Entfernen</strong> über zu viel Erfasstes.
          Gemalte Striche gelten verbindlich – sie ändern nichts an anderer Stelle.
        </p>

        <div className="flex flex-wrap items-center gap-1.5">
          {([['keep', 'Behalten'], ['drop', 'Entfernen'], ['rect', 'Rahmen']] as const).map(
            ([value, label]) => (
              <button key={value} type="button" onClick={() => setMode(value)}
                      className={mode === value ? 'btn-primary btn-sm' : 'btn-ghost btn-sm'}>
                {label}
              </button>
            ))}
          <button type="button" className="btn-ghost btn-sm"
                  onClick={() => setStrokes((p) => p.slice(0, -1))}
                  disabled={strokes.length === 0}>Letzter zurück</button>
          <button type="button" className="btn-ghost btn-sm"
                  onClick={() => { setStrokes([]); setRect(null) }}>Zurücksetzen</button>
          <label className="ml-auto flex items-center gap-1.5 text-[11px] text-ink-400">
            <input type="checkbox" checked={showMask} className="accent-accent-500"
                   onChange={(e) => setShowMask(e.target.checked)} />
            Maske zeigen
          </label>
        </div>

        <div className="relative overflow-hidden rounded-lg border border-ink-700 bg-black">
          <svg ref={svgRef} viewBox={`0 0 ${pxWidth} ${pxHeight}`}
               preserveAspectRatio="xMidYMid meet"
               className="max-h-[52vh] w-full touch-none" onPointerDown={start}>
            <image href={api.imageUrl(projectId, image.id, true)} x={0} y={0}
                   width={pxWidth} height={pxHeight} />
            {showMask && result?.mask_preview && (
              <image href={result.mask_preview} x={0} y={0} width={pxWidth} height={pxHeight}
                     opacity={0.42} style={{ mixBlendMode: 'screen' }} />
            )}
            {rect && (
              <rect x={rect[0]} y={rect[1]} width={rect[2]} height={rect[3]}
                    className="fill-accent-500/10 stroke-accent-400"
                    strokeWidth={pxWidth / 400}
                    strokeDasharray={`${pxWidth / 120} ${pxWidth / 200}`} />
            )}
            {strokes.map((stroke, index) => (
              <polyline key={index} points={stroke.points.map((p) => p.join(',')).join(' ')}
                        fill="none" strokeLinecap="round" strokeLinejoin="round"
                        strokeWidth={settings.brush * 2}
                        className={stroke.foreground ? 'stroke-accent-400/70' : 'stroke-red-400/70'} />
            ))}
          </svg>
          {busy && (
            <div className="absolute inset-0 flex items-center justify-center bg-ink-950/50">
              <Spinner label="wird berechnet…" />
            </div>
          )}
        </div>

        <NumberField label="Pinselbreite" value={settings.brush} min={2} max={80} step={1}
                     unit="px" onChange={(v) => patch({ brush: Math.round(v) })} />

        {result && (
          <Banner kind="success">
            <strong>{result.width_mm.toFixed(1)} × {result.height_mm.toFixed(1)} mm</strong>,
            Fläche {result.area_mm2.toFixed(0)} mm², {result.polygon.length} Punkte
            {result.holes.length > 0 && `, ${result.holes.length} Loch/Löcher`}
            <span className="text-accent-300/70"> · {result.engine_used}, {(result.took_ms / 1000).toFixed(1)} s</span>
          </Banner>
        )}

        <div className="flex flex-wrap gap-2">
          <button type="button" className="btn-ghost" onClick={onPool}>Fotos</button>
          <button type="button" className="btn-ghost" onClick={onBack}>Blatt</button>
          <button type="button" className="btn-ghost flex-1" onClick={() => void run()} disabled={busy}>
            {busy ? 'Wird berechnet…' : 'Neu berechnen'}
          </button>
          <button type="button" className="btn-primary flex-1" disabled={!result || busy}
                  onClick={() => result && onDone(result)}>
            Als Aussparung übernehmen
          </button>
        </div>
      </div>

      <TracePanel settings={settings} onChange={patch} info={info} />
    </div>
  )
}

const defaultCorners = (width: number, height: number): Point[] => [
  [width * 0.15, height * 0.15], [width * 0.85, height * 0.15],
  [width * 0.85, height * 0.85], [width * 0.15, height * 0.85],
]

const clamp = (value: number, min: number, max: number) =>
  Math.min(max, Math.max(min, value))
