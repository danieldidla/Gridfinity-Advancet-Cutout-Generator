import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import type { ImageInfo, Point, TraceResult } from '../lib/types'
import { Banner, Modal, NumberField, Spinner, Toggle } from './ui'

type Step = 'pick' | 'corners' | 'trace'

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
  const [step, setStep] = useState<Step>('pick')
  const [image, setImage] = useState<ImageInfo | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const close = () => { setStep('pick'); setImage(null); setError(null); onClose() }

  const upload = async (file: File) => {
    setBusy('Bild wird hochgeladen…'); setError(null)
    try {
      const uploaded = await api.uploadImage(projectId, file)
      onImagesChanged([...images, uploaded])
      setImage(uploaded)
      setStep('corners')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload fehlgeschlagen')
    } finally { setBusy(null) }
  }

  return (
    <Modal open={open} onClose={close} wide
           title={step === 'pick' ? 'Foto auswählen'
             : step === 'corners' ? 'Blatt ausrichten' : 'Objekt freistellen'}>
      {error && <div className="mb-3"><Banner kind="error" onDismiss={() => setError(null)}>{error}</Banner></div>}
      {busy && <div className="mb-3"><Spinner label={busy} /></div>}

      {step === 'pick' && (
        <PickStep
          images={images} projectId={projectId} onUpload={upload}
          onPick={(picked) => { setImage(picked); setStep(picked.has_rectified ? 'trace' : 'corners') }}
          onDelete={async (id) => {
            await api.deleteImage(projectId, id)
            onImagesChanged(images.filter((i) => i.id !== id))
          }}
        />
      )}

      {step === 'corners' && image && (
        <CornerStep
          projectId={projectId} image={image}
          onBack={() => setStep('pick')}
          onDone={(updated) => {
            onImagesChanged(images.map((i) => (i.id === updated.id ? updated : i)))
            setImage(updated); setStep('trace')
          }}
          onError={setError}
        />
      )}

      {step === 'trace' && image && (
        <TraceStep
          projectId={projectId} image={image}
          onBack={() => setStep('corners')}
          onError={setError}
          onDone={(result) => { onCreate(result, image); close() }}
        />
      )}
    </Modal>
  )
}

/* ---------------------------------------------------------------- pick --- */

function PickStep({ images, projectId, onUpload, onPick, onDelete }: {
  images: ImageInfo[]; projectId: string
  onUpload: (file: File) => void
  onPick: (image: ImageInfo) => void
  onDelete: (id: string) => Promise<void>
}) {
  const fileRef = useRef<HTMLInputElement>(null)
  const cameraRef = useRef<HTMLInputElement>(null)

  return (
    <div className="space-y-4">
      <p className="text-sm leading-relaxed text-ink-300">
        Leg das Objekt auf ein leeres Blatt Papier, sodass das ganze Blatt im Bild ist.
        Fotografiere möglichst senkrecht von oben und achte auf gleichmäßiges Licht ohne
        harte Schatten.
      </p>

      <div className="grid gap-2 sm:grid-cols-2">
        <button type="button" className="btn-primary" onClick={() => cameraRef.current?.click()}>
          📷 Foto aufnehmen
        </button>
        <button type="button" className="btn-ghost" onClick={() => fileRef.current?.click()}>
          ⬆ Datei hochladen
        </button>
      </div>
      <input ref={cameraRef} type="file" accept="image/*" capture="environment" className="hidden"
             onChange={(e) => { const f = e.target.files?.[0]; if (f) onUpload(f); e.target.value = '' }} />
      <input ref={fileRef} type="file" accept="image/*" className="hidden"
             onChange={(e) => { const f = e.target.files?.[0]; if (f) onUpload(f); e.target.value = '' }} />
      <p className="text-[11px] text-ink-500">
        Die Kamera-Schaltfläche funktioniert nur über HTTPS oder auf localhost – das verlangen die Browser.
        Ansonsten das Foto einfach hochladen.
      </p>

      {images.length > 0 && (
        <div>
          <h3 className="label mb-2">Bereits hochgeladen</h3>
          <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {images.map((image) => (
              <li key={image.id} className="group relative">
                <button type="button" onClick={() => onPick(image)}
                        className="block w-full overflow-hidden rounded-lg border border-ink-700
                                   hover:border-accent-500">
                  <img src={api.imageUrl(projectId, image.id)} alt={image.filename}
                       className="aspect-[4/3] w-full object-cover" loading="lazy" />
                  <span className="block truncate px-2 py-1 text-left text-[11px] text-ink-400">
                    {image.has_rectified ? '✓ entzerrt' : 'nicht entzerrt'}
                  </span>
                </button>
                <button type="button" aria-label="Bild löschen"
                        onClick={() => { void onDelete(image.id) }}
                        className="absolute right-1 top-1 rounded bg-black/70 px-1.5 text-xs
                                   text-ink-300 opacity-0 hover:text-red-300 group-hover:opacity-100">
                  ✕
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
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
      clampNumber((event.clientX - rect.left - offsetX) / scale, 0, image.width),
      clampNumber((event.clientY - rect.top - offsetY) / scale, 0, image.height),
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
        Zieh die vier Punkte genau auf die Ecken des Blattes. Je genauer, desto genauer das Maß.
      </p>

      <div className="relative overflow-hidden rounded-lg border border-ink-700 bg-black">
        <svg ref={svgRef} viewBox={`0 0 ${image.width} ${image.height}`}
             preserveAspectRatio="xMidYMid meet"
             className="max-h-[52vh] w-full touch-none">
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
                {['TL', 'TR', 'BR', 'BL'][index]}
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
        <button type="button" className="btn-ghost" onClick={onBack}>Zurück</button>
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

function TraceStep({ projectId, image, onBack, onDone, onError }: {
  projectId: string; image: ImageInfo
  onBack: () => void
  onDone: (result: TraceResult) => void
  onError: (message: string) => void
}) {
  const widthMm = image.trace?.width_mm ?? 210
  const heightMm = image.trace?.height_mm ?? 297
  const pxWidth = Math.round(widthMm * image.px_per_mm)
  const pxHeight = Math.round(heightMm * image.px_per_mm)

  const [rect, setRect] = useState<[number, number, number, number] | null>(null)
  const [strokes, setStrokes] = useState<StrokeDraft[]>([])
  const [mode, setMode] = useState<'rect' | 'keep' | 'drop'>('rect')
  const [brush, setBrush] = useState(10)
  const [simplify, setSimplify] = useState(0.25)
  const [smooth, setSmooth] = useState(0)
  const [holes, setHoles] = useState(true)
  const [result, setResult] = useState<TraceResult | null>(null)
  const [busy, setBusy] = useState(false)

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
      Math.round(clampNumber((event.clientX - box.left - offsetX) / scale, 0, pxWidth)),
      Math.round(clampNumber((event.clientY - box.top - offsetY) / scale, 0, pxHeight)),
    ]
  }, [pxWidth, pxHeight])

  const run = async () => {
    setBusy(true)
    try {
      const traced = await api.trace(projectId, image.id, {
        rect, strokes: strokes.map((s) => ({ points: s.points, foreground: s.foreground })),
        brush, simplify_mm: simplify, smooth_mm: smooth, include_holes: holes,
      })
      setResult(traced)
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Freistellen fehlgeschlagen')
    } finally { setBusy(false) }
  }

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
          copy[copy.length - 1] = {
            ...copy[copy.length - 1],
            points: [...copy[copy.length - 1].points, point],
          }
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

  return (
    <div className="space-y-3">
      <p className="text-sm text-ink-300">
        Zieh zuerst einen Rahmen um das Objekt. Wenn die Kontur noch nicht stimmt, male mit
        „Behalten“ über fehlende Bereiche und mit „Entfernen“ über zu viel Erfasstes.
      </p>

      <div className="flex flex-wrap items-center gap-2">
        {([['rect', 'Rahmen'], ['keep', 'Behalten'], ['drop', 'Entfernen']] as const).map(([value, label]) => (
          <button key={value} type="button"
                  onClick={() => setMode(value)}
                  className={mode === value ? 'btn-primary btn-sm' : 'btn-ghost btn-sm'}>
            {label}
          </button>
        ))}
        <button type="button" className="btn-ghost btn-sm"
                onClick={() => { setStrokes([]); setRect(null); setResult(null) }}>
          Zurücksetzen
        </button>
      </div>

      <div className="overflow-hidden rounded-lg border border-ink-700 bg-black">
        <svg ref={svgRef} viewBox={`0 0 ${pxWidth} ${pxHeight}`}
             preserveAspectRatio="xMidYMid meet"
             className="max-h-[46vh] w-full touch-none"
             onPointerDown={start}>
          <image href={api.imageUrl(projectId, image.id, true)} x={0} y={0}
                 width={pxWidth} height={pxHeight} />
          {result?.mask_preview && (
            <image href={result.mask_preview} x={0} y={0} width={pxWidth} height={pxHeight}
                   opacity={0.38} style={{ mixBlendMode: 'screen' }} />
          )}
          {rect && (
            <rect x={rect[0]} y={rect[1]} width={rect[2]} height={rect[3]}
                  className="fill-accent-500/10 stroke-accent-400"
                  strokeWidth={pxWidth / 400} strokeDasharray={`${pxWidth / 120} ${pxWidth / 200}`} />
          )}
          {strokes.map((stroke, index) => (
            <polyline key={index}
                      points={stroke.points.map((p) => p.join(',')).join(' ')}
                      fill="none" strokeLinecap="round" strokeLinejoin="round"
                      strokeWidth={brush * 2}
                      className={stroke.foreground ? 'stroke-accent-400/70' : 'stroke-red-400/70'} />
          ))}
        </svg>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <NumberField label="Pinselbreite" value={brush} min={2} max={60} step={1} unit="px"
                     onChange={(v) => setBrush(Math.round(v))} />
        <NumberField label="Kontur vereinfachen" value={simplify} min={0} max={3} step={0.05}
                     onChange={(v) => setSimplify(v)}
                     hint="Höher = weniger Punkte, gröbere Kontur." />
        <NumberField label="Glätten" value={smooth} min={0} max={4} step={0.1}
                     onChange={(v) => setSmooth(v)}
                     hint="Bügelt ausgefranste Ränder aus." />
        <div className="flex items-end">
          <Toggle label="Innenlöcher übernehmen" checked={holes} onChange={setHoles} />
        </div>
      </div>

      {result && (
        <Banner kind="success">
          Kontur gefunden: <strong>{result.width_mm.toFixed(1)} × {result.height_mm.toFixed(1)} mm</strong>,
          Fläche {result.area_mm2.toFixed(0)} mm², {result.polygon.length} Punkte
          {result.holes.length > 0 && `, ${result.holes.length} Loch/Löcher`}.
        </Banner>
      )}

      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn-ghost" onClick={onBack}>Zurück</button>
        <button type="button" className="btn-ghost flex-1" onClick={run} disabled={busy}>
          {busy ? 'Wird berechnet…' : result ? 'Neu berechnen' : 'Kontur berechnen'}
        </button>
        <button type="button" className="btn-primary flex-1"
                disabled={!result} onClick={() => result && onDone(result)}>
          Als Aussparung übernehmen
        </button>
      </div>
    </div>
  )
}

const defaultCorners = (width: number, height: number): Point[] => [
  [width * 0.15, height * 0.15], [width * 0.85, height * 0.15],
  [width * 0.85, height * 0.85], [width * 0.15, height * 0.85],
]

const clampNumber = (value: number, min: number, max: number) =>
  Math.min(max, Math.max(min, value))
