import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import BinPanel from '../components/BinPanel'
import CutoutPanel from '../components/CutoutPanel'
import LayoutEditor from '../components/LayoutEditor'
import PhotoWizard from '../components/PhotoWizard'
import ScanWizard from '../components/ScanWizard'
import { Banner, Modal, Spinner } from '../components/ui'
import Viewer from '../three/Viewer'
import { api, downloadExport } from '../lib/api'
import { circlePolygon, polygonBounds, rectanglePolygon, usableDepth } from '../lib/defaults'
import { useEditor } from '../lib/store'
import type { ModelStats, ScanInfo, TraceResult } from '../lib/types'

type Tab = '3d' | 'layout'
type Panel = 'bin' | 'cutout'

export default function Editor() {
  const { projectId = '' } = useParams()
  const store = useEditor()
  const {
    state, name, images, scans, saveState, saveError, loading, loadError,
  } = store

  const [tab, setTab] = useState<Tab>('3d')
  const [panel, setPanel] = useState<Panel>('bin')
  const [dragging, setDragging] = useState(false)
  const [viewer, setViewer] = useState({ loading: false, error: null as string | null })
  const [stats, setStats] = useState<ModelStats | null>(null)
  const [photoOpen, setPhotoOpen] = useState(false)
  const [scanOpen, setScanOpen] = useState(false)
  const [shapeOpen, setShapeOpen] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [exporting, setExporting] = useState(false)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    void store.load(projectId)
    return () => store.reset()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  const selected = state.cutouts.find((c) => c.id === state.view.selected_cutout) ?? null
  useEffect(() => { if (selected) setPanel('cutout') }, [selected?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const buildPayload = useMemo(
    () => ({ bin: state.bin, cutouts: state.cutouts.filter((c) => c.enabled) }),
    [state.bin, state.cutouts],
  )

  // Statistics follow the model but must not chase every slider frame.
  useEffect(() => {
    if (dragging) return
    const timer = setTimeout(() => {
      api.stats(buildPayload).then(setStats).catch(() => setStats(null))
    }, 260)
    return () => clearTimeout(timer)
  }, [buildPayload, dragging])

  // Keep a thumbnail on the project card, cheaply and not too often.
  useEffect(() => {
    if (!canvasRef.current || viewer.loading || !projectId) return
    const timer = setTimeout(() => {
      try {
        const url = canvasRef.current?.toDataURL('image/jpeg', 0.5)
        if (url && url.length < 380_000) void api.setThumbnail(projectId, url)
      } catch { /* tainted canvas or similar: not worth reporting */ }
    }, 4000)
    return () => clearTimeout(timer)
  }, [buildPayload, viewer.loading, projectId])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' ||
          target.tagName === 'SELECT') return
      const mod = event.ctrlKey || event.metaKey
      if (mod && event.key.toLowerCase() === 'z') {
        event.preventDefault()
        if (event.shiftKey) store.redo(); else store.undo()
      } else if (mod && event.key.toLowerCase() === 'y') {
        event.preventDefault(); store.redo()
      } else if (mod && event.key.toLowerCase() === 's') {
        event.preventDefault(); void store.flush()
      } else if (event.key === 'Delete' && selected) {
        store.removeCutout(selected.id)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [store, selected])

  const addFromTrace = useCallback((result: TraceResult) => {
    const bounds = polygonBounds(result.polygon)
    store.addCutout({
      name: 'Objekt aus Foto',
      polygon: result.polygon,
      holes: result.holes,
      depth: Math.min(usableDepth(state.bin), Math.max(4, Math.min(bounds.width, bounds.height) * 0.6)),
      source: { kind: 'image', id: null, label: 'Foto' },
    })
    setPanel('cutout')
  }, [store, state.bin])

  const addFromScan = useCallback((scan: ScanInfo) => {
    const height = typeof scan.dimensions?.height_mm === 'number'
      ? scan.dimensions.height_mm as number : 10
    store.addCutout({
      name: scan.name,
      polygon: [],
      mesh_source: `meshes/${scan.id}.npz`,
      depth: Math.min(usableDepth(state.bin), height),
      clearance: 0.4,
      source: { kind: 'scan', id: scan.id, label: '3D-Aufnahme' },
    })
    setPanel('cutout')
  }, [store, state.bin])

  const exportModel = async (format: 'stl' | '3mf') => {
    setExporting(true)
    try {
      await store.flush()
      await downloadExport(format, buildPayload, name || 'gridfinity')
    } catch (error) {
      setViewer((v) => ({ ...v, error: error instanceof Error ? error.message : 'Export fehlgeschlagen' }))
    } finally { setExporting(false) }
  }

  if (loading) {
    return <div className="flex h-full items-center justify-center"><Spinner label="Projekt wird geladen…" /></div>
  }
  if (loadError) {
    return (
      <div className="mx-auto max-w-md p-6">
        <Banner kind="error">{loadError}</Banner>
        <Link to="/" className="btn-ghost mt-4">Zur Projektliste</Link>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex shrink-0 items-center gap-2 border-b border-ink-800 bg-ink-900/80 px-3 py-2">
        <Link to="/" className="shrink-0 rounded px-2 py-1 text-ink-400 hover:bg-ink-800
                                hover:text-ink-100" aria-label="Zur Projektliste">←</Link>
        <input
          className="min-w-0 flex-1 rounded bg-transparent px-2 py-1 text-sm font-medium
                     text-ink-50 outline-none hover:bg-ink-800/60 focus:bg-ink-800"
          value={name} onChange={(e) => store.rename(e.target.value)} aria-label="Projektname"
        />
        <SaveBadge state={saveState} />
        <div className="hidden items-center gap-1 sm:flex">
          <button type="button" className="btn-ghost btn-sm" onClick={store.undo}
                  disabled={store.past.length === 0} title="Rückgängig (Strg+Z)">↶</button>
          <button type="button" className="btn-ghost btn-sm" onClick={store.redo}
                  disabled={store.future.length === 0} title="Wiederholen (Strg+Umschalt+Z)">↷</button>
        </div>
        <button type="button" className="btn-ghost btn-sm lg:hidden"
                onClick={() => setSidebarOpen(true)}>Einstellungen</button>
      </header>

      {saveError && <div className="px-3 pt-2"><Banner kind="error">{saveError}</Banner></div>}

      <div className="flex min-h-0 flex-1">
        <main className="relative flex min-w-0 flex-1 flex-col">
          <div className="absolute left-3 top-3 z-10 flex gap-1 rounded-lg bg-ink-900/85 p-1">
            {([['3d', '3D'], ['layout', 'Anordnung']] as const).map(([value, label]) => (
              <button key={value} type="button" onClick={() => setTab(value)}
                      className={`rounded px-3 py-1 text-xs font-medium ${
                        tab === value ? 'bg-accent-600 text-white' : 'text-ink-300 hover:bg-ink-800'}`}>
                {label}
              </button>
            ))}
          </div>

          {viewer.loading && (
            <div className="absolute right-3 top-3 z-10 rounded-lg bg-ink-900/85 px-2 py-1">
              <Spinner label="Modell wird gebaut" />
            </div>
          )}
          {viewer.error && (
            <div className="absolute inset-x-3 top-14 z-10">
              <Banner kind="error" onDismiss={() => setViewer((v) => ({ ...v, error: null }))}>
                {viewer.error}
              </Banner>
            </div>
          )}

          <div className="min-h-0 flex-1">
            {tab === '3d' ? (
              <Viewer
                bin={state.bin} cutouts={state.cutouts}
                selectedId={state.view.selected_cutout}
                dragging={dragging} showGrid={state.view.show_grid}
                onStatus={setViewer}
                onCanvasReady={(canvas) => { canvasRef.current = canvas }}
              />
            ) : (
              <LayoutEditor
                bin={state.bin} cutouts={state.cutouts}
                selectedId={state.view.selected_cutout}
                onSelect={store.select}
                onMove={(id, x, y, final) => {
                  setDragging(!final)
                  store.updateCutout(id, { x, y }, false)
                  if (final) store.commitHistory()
                }}
                onRotate={(id, rotation, final) => {
                  setDragging(!final)
                  store.updateCutout(id, { rotation }, false)
                  if (final) store.commitHistory()
                }}
              />
            )}
          </div>

          <StatsBar stats={stats} />
        </main>

        <aside className={`${sidebarOpen ? 'fixed inset-0 z-40 bg-ink-950' : 'hidden'}
                           w-full shrink-0 border-l border-ink-800 bg-ink-900/40
                           lg:static lg:z-0 lg:block lg:w-[340px]`}>
          <div className="flex h-full flex-col">
            <div className="flex items-center gap-1 border-b border-ink-800 p-2">
              <button type="button" onClick={() => setPanel('bin')}
                      className={`flex-1 rounded px-3 py-1.5 text-xs font-medium ${
                        panel === 'bin' ? 'bg-ink-700 text-ink-50' : 'text-ink-400 hover:bg-ink-800'}`}>
                Behälter
              </button>
              <button type="button" onClick={() => setPanel('cutout')} disabled={!selected}
                      className={`flex-1 rounded px-3 py-1.5 text-xs font-medium disabled:opacity-40 ${
                        panel === 'cutout' ? 'bg-ink-700 text-ink-50' : 'text-ink-400 hover:bg-ink-800'}`}>
                Aussparung
              </button>
              <button type="button" className="btn-ghost btn-sm lg:hidden"
                      onClick={() => setSidebarOpen(false)}>✕</button>
            </div>

            <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto">
              <CutoutList
                cutouts={state.cutouts}
                selectedId={state.view.selected_cutout}
                onSelect={(id) => { store.select(id); setPanel('cutout') }}
                onToggle={(id, enabled) => store.updateCutout(id, { enabled })}
                onRemove={store.removeCutout}
                onDuplicate={store.duplicateCutout}
                onReorder={store.reorderCutout}
                onAddPhoto={() => setPhotoOpen(true)}
                onAddScan={() => setScanOpen(true)}
                onAddShape={() => setShapeOpen(true)}
              />
              {panel === 'bin'
                ? <BinPanel bin={state.bin}
                            onChange={(patch, final) => store.setBin(patch, final !== false)} />
                : selected && (
                    <CutoutPanel
                      cutout={selected} bin={state.bin}
                      onChange={(patch, final) => {
                        store.updateCutout(selected.id, patch, final !== false)
                        if (final !== false) store.commitHistory()
                      }}
                    />
                  )}
            </div>

            <div className="shrink-0 space-y-2 border-t border-ink-800 p-3">
              <div className="grid grid-cols-2 gap-2">
                <button type="button" className="btn-primary" disabled={exporting}
                        onClick={() => void exportModel('3mf')}>
                  {exporting ? '…' : '3MF laden'}
                </button>
                <button type="button" className="btn-ghost" disabled={exporting}
                        onClick={() => void exportModel('stl')}>STL laden</button>
              </div>
              <p className="text-[11px] leading-snug text-ink-500">
                3MF ist die bessere Wahl: Millimeter sind darin festgeschrieben und die Datei
                ist deutlich kleiner.
              </p>
            </div>
          </div>
        </aside>
      </div>

      <PhotoWizard
        open={photoOpen} projectId={projectId} images={images}
        onClose={() => setPhotoOpen(false)}
        onImagesChanged={store.setImages}
        onCreate={(result) => addFromTrace(result)}
      />
      <ScanWizard
        open={scanOpen} projectId={projectId} scans={scans}
        onClose={() => setScanOpen(false)}
        onScansChanged={store.setScans}
        onUseMesh={addFromScan}
      />
      <ShapeDialog
        open={shapeOpen} onClose={() => setShapeOpen(false)}
        maxDepth={usableDepth(state.bin)}
        onCreate={(cutout) => { store.addCutout(cutout); setShapeOpen(false); setPanel('cutout') }}
      />
    </div>
  )
}

/* ------------------------------------------------------------ fragments --- */

function SaveBadge({ state }: { state: ReturnType<typeof useEditor.getState>['saveState'] }) {
  const map = {
    idle: { text: '', className: '' },
    dirty: { text: 'nicht gespeichert', className: 'text-ink-500' },
    saving: { text: 'speichert…', className: 'text-ink-400' },
    saved: { text: 'gespeichert', className: 'text-accent-400' },
    error: { text: 'Fehler', className: 'text-red-400' },
  }[state]
  if (!map.text) return null
  return <span className={`shrink-0 text-[11px] ${map.className}`}>{map.text}</span>
}

function StatsBar({ stats }: { stats: ModelStats | null }) {
  if (!stats) return null
  return (
    <div className="shrink-0 border-t border-ink-800 bg-ink-900/70 px-3 py-1.5">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-ink-400">
        <span>Maß <span className="font-mono text-ink-200">
          {stats.width_mm.toFixed(1)} × {stats.depth_mm.toFixed(1)} × {stats.height_mm.toFixed(1)} mm
        </span></span>
        <span>Material <span className="font-mono text-ink-200">{stats.material_cm3.toFixed(1)} cm³</span></span>
        <span>Dreiecke <span className="font-mono text-ink-200">{stats.triangles.toLocaleString('de-DE')}</span></span>
        <span className="text-ink-600">{stats.build_ms.toFixed(0)} ms</span>
      </div>
      {stats.warnings.length > 0 && (
        <ul className="mt-1 space-y-0.5">
          {stats.warnings.map((warning) => (
            <li key={warning} className="text-[11px] text-amber-400">⚠ {warning}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

function CutoutList({
  cutouts, selectedId, onSelect, onToggle, onRemove, onDuplicate, onReorder,
  onAddPhoto, onAddScan, onAddShape,
}: {
  cutouts: ReturnType<typeof useEditor.getState>['state']['cutouts']
  selectedId: string | null
  onSelect: (id: string) => void
  onToggle: (id: string, enabled: boolean) => void
  onRemove: (id: string) => void
  onDuplicate: (id: string) => void
  onReorder: (id: string, direction: -1 | 1) => void
  onAddPhoto: () => void
  onAddScan: () => void
  onAddShape: () => void
}) {
  return (
    <section className="border-b border-ink-800 p-3">
      <h2 className="panel-title mb-2"><span>Aussparungen ({cutouts.length})</span></h2>

      <div className="mb-3 grid grid-cols-3 gap-1.5">
        <button type="button" className="btn-ghost btn-sm flex-col !py-2" onClick={onAddPhoto}>
          <span className="text-base">📷</span><span>Foto</span>
        </button>
        <button type="button" className="btn-ghost btn-sm flex-col !py-2" onClick={onAddScan}>
          <span className="text-base">🧊</span><span>3D-Scan</span>
        </button>
        <button type="button" className="btn-ghost btn-sm flex-col !py-2" onClick={onAddShape}>
          <span className="text-base">▭</span><span>Form</span>
        </button>
      </div>

      {cutouts.length === 0 ? (
        <p className="text-xs leading-relaxed text-ink-500">
          Noch keine Aussparung. Fang mit einem Foto an – oder setz eine einfache Grundform ein.
        </p>
      ) : (
        <ul className="space-y-1">
          {cutouts.map((cutout, index) => (
            <li key={cutout.id}
                className={`flex items-center gap-1.5 rounded-lg border px-2 py-1.5 ${
                  cutout.id === selectedId
                    ? 'border-accent-600 bg-accent-900/25'
                    : 'border-ink-800 bg-ink-950/40 hover:border-ink-700'}`}>
              <input type="checkbox" checked={cutout.enabled} className="accent-accent-500"
                     aria-label={`${cutout.name} aktiv`}
                     onChange={(e) => onToggle(cutout.id, e.target.checked)} />
              <button type="button" className="min-w-0 flex-1 text-left"
                      onClick={() => onSelect(cutout.id)}>
                <span className="block truncate text-xs text-ink-100">{cutout.name}</span>
                <span className="text-[10px] text-ink-500">
                  {cutout.mesh_source ? '3D-Aufnahme' : `${cutout.polygon.length} Punkte`}
                  {' · '}{cutout.depth.toFixed(1)} mm tief
                </span>
              </button>
              <div className="flex shrink-0 flex-col">
                <button type="button" aria-label="Nach oben" className="px-1 text-[9px] text-ink-500
                        hover:text-ink-200 disabled:opacity-30"
                        disabled={index === 0} onClick={() => onReorder(cutout.id, -1)}>▲</button>
                <button type="button" aria-label="Nach unten" className="px-1 text-[9px] text-ink-500
                        hover:text-ink-200 disabled:opacity-30"
                        disabled={index === cutouts.length - 1}
                        onClick={() => onReorder(cutout.id, 1)}>▼</button>
              </div>
              <button type="button" aria-label="Duplizieren"
                      className="px-1 text-xs text-ink-500 hover:text-ink-200"
                      onClick={() => onDuplicate(cutout.id)}>⧉</button>
              <button type="button" aria-label="Löschen"
                      className="px-1 text-xs text-ink-500 hover:text-red-400"
                      onClick={() => onRemove(cutout.id)}>✕</button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function ShapeDialog({ open, onClose, onCreate, maxDepth }: {
  open: boolean
  onClose: () => void
  maxDepth: number
  onCreate: (cutout: Record<string, unknown>) => void
}) {
  const [kind, setKind] = useState<'rect' | 'circle'>('rect')
  const [width, setWidth] = useState(30)
  const [height, setHeight] = useState(20)
  const [diameter, setDiameter] = useState(25)
  const [depth, setDepth] = useState(Math.min(10, maxDepth))

  return (
    <Modal open={open} onClose={onClose} title="Grundform einfügen">
      <div className="space-y-4">
        <div className="flex gap-2">
          {([['rect', 'Rechteck'], ['circle', 'Kreis']] as const).map(([value, label]) => (
            <button key={value} type="button" onClick={() => setKind(value)}
                    className={kind === value ? 'btn-primary flex-1' : 'btn-ghost flex-1'}>{label}</button>
          ))}
        </div>

        {kind === 'rect' ? (
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="label mb-1">Breite (mm)</span>
              <input className="field" type="number" value={width} min={1} step={0.5}
                     onChange={(e) => setWidth(Number(e.target.value))} />
            </label>
            <label className="block">
              <span className="label mb-1">Tiefe (mm)</span>
              <input className="field" type="number" value={height} min={1} step={0.5}
                     onChange={(e) => setHeight(Number(e.target.value))} />
            </label>
          </div>
        ) : (
          <label className="block">
            <span className="label mb-1">Durchmesser (mm)</span>
            <input className="field" type="number" value={diameter} min={1} step={0.5}
                   onChange={(e) => setDiameter(Number(e.target.value))} />
          </label>
        )}

        <label className="block">
          <span className="label mb-1">Tiefe der Aussparung (mm)</span>
          <input className="field" type="number" value={depth} min={0.2} step={0.5}
                 onChange={(e) => setDepth(Number(e.target.value))} />
          <span className="mt-1 block text-[11px] text-ink-500">
            Ohne Durchbruch sind maximal {maxDepth.toFixed(1)} mm möglich.
          </span>
        </label>

        <button type="button" className="btn-primary w-full"
                onClick={() => onCreate({
                  name: kind === 'rect' ? 'Rechteck' : 'Kreis',
                  polygon: kind === 'rect'
                    ? rectanglePolygon(width, height)
                    : circlePolygon(diameter),
                  depth,
                  clearance: 0,
                  source: { kind: 'shape', id: null, label: 'Grundform' },
                })}>
          Einfügen
        </button>
      </div>
    </Modal>
  )
}
