import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import type { BoardInfo, Coverage, Job, ScanInfo, ShotInfo } from '../lib/types'
import CoverageWheel from './CoverageWheel'
import { Banner, Modal, NumberField, Section, Spinner, Toggle } from './ui'

interface Props {
  open: boolean
  projectId: string
  scans: ScanInfo[]
  onClose: () => void
  onScansChanged: (scans: ScanInfo[]) => void
  onUseMesh: (scan: ScanInfo) => void
}

export default function ScanWizard({
  open, projectId, scans, onClose, onScansChanged, onUseMesh,
}: Props) {
  const [scanId, setScanId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [board, setBoard] = useState<BoardInfo | null>(null)
  const scan = scans.find((s) => s.id === scanId) ?? null

  // The reconstruction libraries are an optional install, so ask the server
  // whether it can do the work before offering to start it.
  useEffect(() => {
    if (!open || board) return
    api.boardInfo().then(setBoard).catch(() => undefined)
  }, [open, board])

  const refresh = useCallback(async () => {
    try { onScansChanged(await api.listScans(projectId)) } catch { /* ignore */ }
  }, [projectId, onScansChanged])

  const create = async () => {
    try {
      const created = await api.createScan(projectId, `Aufnahme ${scans.length + 1}`)
      onScansChanged([...scans, created])
      setScanId(created.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Aufnahme konnte nicht angelegt werden')
    }
  }

  return (
    <Modal open={open} onClose={() => { setScanId(null); onClose() }} wide
           title={scan ? `3D-Aufnahme · ${scan.name}` : '3D-Aufnahme'}>
      {error && <div className="mb-3"><Banner kind="error" onDismiss={() => setError(null)}>{error}</Banner></div>}

      {board && !board.reconstruction_available && (
        <div className="mb-3">
          <Banner kind="warn">
            Diese Installation kann keine 3D-Aufnahmen berechnen &ndash; SciPy und
            scikit-image wurden nicht mitinstalliert (zusammen rund 220 MB).
            Nachr&uuml;sten mit{' '}
            <code className="rounded bg-ink-950/60 px-1">
              pip install -r backend/requirements-scan.txt
            </code>{' '}
            und die Dienste neu starten. Fotos und Aussparungen funktionieren
            unabh&auml;ngig davon.
          </Banner>
        </div>
      )}

      {!scan ? (
        <Intro scans={scans} onCreate={create} onOpen={setScanId}
               disabled={board ? !board.reconstruction_available : false}
               onDelete={async (id) => {
                 await api.deleteScan(projectId, id)
                 onScansChanged(scans.filter((s) => s.id !== id))
               }} />
      ) : (
        <Capture projectId={projectId} scan={scan} onBack={() => setScanId(null)}
                 onRefresh={refresh} onError={setError}
                 onUseMesh={() => { onUseMesh(scan); setScanId(null); onClose() }} />
      )}
    </Modal>
  )
}

/* --------------------------------------------------------------- intro --- */

function Intro({ scans, onCreate, onOpen, onDelete, disabled }: {
  scans: ScanInfo[]
  onCreate: () => void
  onOpen: (id: string) => void
  onDelete: (id: string) => Promise<void>
  disabled: boolean
}) {
  return (
    <div className="space-y-4">
      <Banner kind="info">
        So entsteht aus Fotos eine echte 3D-Form: Das Objekt wird <strong>mit der Unterseite
        nach oben</strong> mittig auf das gedruckte Markerboard gelegt. Daraus berechnet der
        Server die Hüllform des Objekts – und die ergibt die Tasche.
      </Banner>

      <ol className="space-y-2 text-sm text-ink-300">
        <li className="flex gap-2"><span className="font-mono text-accent-400">1.</span>
          <span>
            Board ausdrucken – <a href="/api/scan-board.pdf" target="_blank" rel="noreferrer"
              className="text-accent-400 underline">PDF herunterladen</a>.
            Unbedingt in Originalgröße drucken, ohne „an Seite anpassen“.
          </span></li>
        <li className="flex gap-2"><span className="font-mono text-accent-400">2.</span>
          <span>Board flach auf den Tisch legen, das Objekt kopfüber in die Mitte stellen.</span></li>
        <li className="flex gap-2"><span className="font-mono text-accent-400">3.</span>
          <span>Rundherum fotografieren – flach, schräg und steil. Die Anzeige sagt dir, wo noch etwas fehlt.</span></li>
        <li className="flex gap-2"><span className="font-mono text-accent-400">4.</span>
          <span>Berechnung starten. Das dauert je nach Bildzahl einige Minuten.</span></li>
      </ol>

      <button type="button" className="btn-primary w-full" onClick={onCreate}
              disabled={disabled}>
        Neue Aufnahme beginnen
      </button>

      {scans.length > 0 && (
        <div>
          <h3 className="label mb-2">Vorhandene Aufnahmen</h3>
          <ul className="space-y-1.5">
            {scans.map((scan) => (
              <li key={scan.id} className="flex items-center gap-2 rounded-lg border
                                           border-ink-800 bg-ink-950/50 px-3 py-2">
                <button type="button" className="min-w-0 flex-1 text-left"
                        onClick={() => onOpen(scan.id)}>
                  <span className="block truncate text-sm text-ink-100">{scan.name}</span>
                  <span className="text-[11px] text-ink-500">
                    {scan.shot_count} Bilder · <StatusLabel status={scan.status} />
                    {scan.dimensions && typeof scan.dimensions.width_mm === 'number' && (
                      <> · {(scan.dimensions.width_mm as number).toFixed(1)} ×{' '}
                        {(scan.dimensions.depth_mm as number).toFixed(1)} ×{' '}
                        {(scan.dimensions.height_mm as number).toFixed(1)} mm</>
                    )}
                  </span>
                </button>
                <button type="button" className="btn-danger btn-sm"
                        onClick={() => { void onDelete(scan.id) }}>Löschen</button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function StatusLabel({ status }: { status: ScanInfo['status'] }) {
  const map: Record<ScanInfo['status'], string> = {
    capturing: 'Aufnahme läuft',
    processing: 'wird berechnet',
    ready: 'fertig',
    failed: 'fehlgeschlagen',
  }
  return <span>{map[status]}</span>
}

/* ------------------------------------------------------------- capture --- */

function Capture({ projectId, scan, onBack, onRefresh, onError, onUseMesh }: {
  projectId: string
  scan: ScanInfo
  onBack: () => void
  onRefresh: () => Promise<void>
  onError: (message: string) => void
  onUseMesh: () => void
}) {
  const [shots, setShots] = useState<ShotInfo[]>([])
  const [coverage, setCoverage] = useState<Coverage | null>(scan.coverage)
  const [hint, setHint] = useState<string | null>(null)
  const [uploading, setUploading] = useState(0)
  const [job, setJob] = useState<Job | null>(null)
  const [settings, setSettings] = useState({
    voxel_mm: 0.5, max_height_mm: 120, extent_mm: 160,
    threshold: 45, smooth: 0.8, extend_beyond_board: true,
  })
  const cameraRef = useRef<HTMLInputElement>(null)
  const filesRef = useRef<HTMLInputElement>(null)

  const loadShots = useCallback(async () => {
    try {
      setShots(await api.listShots(projectId, scan.id))
      setCoverage(await fetch(
        `/api/projects/${projectId}/scans/${scan.id}/coverage`,
        { credentials: 'same-origin' }).then((r) => r.json()))
    } catch { /* ignore */ }
  }, [projectId, scan.id])

  useEffect(() => { void loadShots() }, [loadShots])

  const upload = async (files: FileList) => {
    const list = Array.from(files)
    setUploading(list.length)
    for (const file of list) {
      try {
        const response = await api.addShot(projectId, scan.id, file)
        setCoverage(response.coverage)
        setHint(response.hint)
        setShots((previous) => [...previous, response.shot])
      } catch (e) {
        onError(e instanceof Error ? e.message : 'Aufnahme konnte nicht gespeichert werden')
        break
      } finally {
        setUploading((n) => n - 1)
      }
    }
    void onRefresh()
  }

  const start = async () => {
    try {
      setJob(await api.reconstruct(projectId, scan.id, settings))
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Berechnung konnte nicht gestartet werden')
    }
  }

  // Poll while a reconstruction is running. It takes minutes, so a one-second
  // poll is plenty and keeps the progress bar honest.
  useEffect(() => {
    if (!job || job.status === 'done' || job.status === 'failed') return
    const timer = setInterval(async () => {
      try {
        const updated = await api.job(job.id)
        setJob(updated)
        if (updated.status === 'done' || updated.status === 'failed') {
          await onRefresh()
        }
      } catch { /* keep polling */ }
    }, 1200)
    return () => clearInterval(timer)
  }, [job, onRefresh])

  useEffect(() => {
    if (scan.status === 'processing' && !job) {
      void api.job('').catch(() => undefined)
    }
  }, [scan.status, job])

  const usable = shots.filter((s) => s.usable).length
  const running = job && (job.status === 'queued' || job.status === 'running')
  const ready = scan.status === 'ready' && scan.has_mesh

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-[auto,1fr]">
        <CoverageWheel coverage={coverage} />
        <div className="space-y-3">
          <div className="rounded-lg bg-ink-950/60 px-3 py-2 text-sm">
            <div className="flex justify-between"><span className="text-ink-400">Bilder</span>
              <span className="font-mono">{shots.length}</span></div>
            <div className="flex justify-between"><span className="text-ink-400">davon verwertbar</span>
              <span className={`font-mono ${usable < 8 ? 'text-amber-400' : 'text-accent-400'}`}>{usable}</span></div>
          </div>

          {hint && <Banner kind={hint.startsWith('Aufnahme in Ordnung') ? 'success' : 'warn'}
                           onDismiss={() => setHint(null)}>{hint}</Banner>}

          <div className="grid gap-2 sm:grid-cols-2">
            <button type="button" className="btn-primary" onClick={() => cameraRef.current?.click()}
                    disabled={Boolean(running)}>📷 Aufnehmen</button>
            <button type="button" className="btn-ghost" onClick={() => filesRef.current?.click()}
                    disabled={Boolean(running)}>⬆ Bilder hochladen</button>
          </div>
          <input ref={cameraRef} type="file" accept="image/*" capture="environment" className="hidden"
                 onChange={(e) => { if (e.target.files?.length) void upload(e.target.files); e.target.value = '' }} />
          <input ref={filesRef} type="file" accept="image/*" multiple className="hidden"
                 onChange={(e) => { if (e.target.files?.length) void upload(e.target.files); e.target.value = '' }} />
          {uploading > 0 && <Spinner label={`${uploading} Bild(er) werden verarbeitet…`} />}

          <p className="text-[11px] leading-relaxed text-ink-500">
            Wichtig: Auch <strong>flache</strong> Aufnahmen knapp über der Tischkante machen. Nur
            die begrenzen die Höhe des Objekts – von oben allein lässt sie sich nicht bestimmen.
          </p>
        </div>
      </div>

      {shots.length > 0 && (
        <div className="scrollbar-thin flex gap-2 overflow-x-auto pb-1">
          {shots.map((shot) => (
            <div key={shot.id} className="relative shrink-0">
              <img src={api.shotUrl(projectId, scan.id, shot.id)} alt={`Aufnahme ${shot.sequence}`}
                   loading="lazy"
                   className={`h-20 w-28 rounded border object-cover ${
                     shot.usable ? 'border-ink-700' : 'border-amber-700 opacity-60'}`} />
              <button type="button" aria-label="Aufnahme löschen"
                      className="absolute right-0.5 top-0.5 rounded bg-black/70 px-1 text-xs text-ink-300
                                 hover:text-red-300"
                      onClick={async () => {
                        await api.deleteShot(projectId, scan.id, shot.id)
                        void loadShots()
                      }}>✕</button>
              {shot.elevation !== null && (
                <span className="absolute bottom-0.5 left-0.5 rounded bg-black/70 px-1
                                 text-[9px] font-mono text-ink-300">
                  {shot.elevation.toFixed(0)}°
                </span>
              )}
            </div>
          ))}
        </div>
      )}

      <Section title="Berechnung" defaultOpen={false}>
        <NumberField label="Auflösung (Voxelgröße)" value={settings.voxel_mm} min={0.2} max={2} step={0.1}
                     onChange={(v) => setSettings((s) => ({ ...s, voxel_mm: v }))}
                     hint="Kleiner = feiner, aber deutlich langsamer. 0,5 mm ist ein guter Kompromiss." />
        <NumberField label="Maximale Objekthöhe" value={settings.max_height_mm} min={10} max={250} step={5}
                     onChange={(v) => setSettings((s) => ({ ...s, max_height_mm: v }))} />
        <NumberField label="Schwellwert Freistellung" value={settings.threshold} min={10} max={150} step={1} unit=""
                     onChange={(v) => setSettings((s) => ({ ...s, threshold: Math.round(v) }))}
                     hint="Niedriger erfasst mehr, nimmt aber eher Schatten mit." />
        <NumberField label="Glättung" value={settings.smooth} min={0} max={2.5} step={0.1} unit=""
                     onChange={(v) => setSettings((s) => ({ ...s, smooth: v }))} />
        <Toggle label="Objekt darf über das Board hinausragen"
                checked={settings.extend_beyond_board}
                onChange={(v) => setSettings((s) => ({ ...s, extend_beyond_board: v }))}
                hint="Nötig bei flachen Aufnahmen hoher Objekte. Abschalten, wenn der Hintergrund unruhig ist." />
      </Section>

      {running && job && (
        <div className="space-y-2">
          <div className="h-2 overflow-hidden rounded-full bg-ink-800">
            <div className="h-full bg-accent-500 transition-all"
                 style={{ width: `${Math.round(job.progress * 100)}%` }} />
          </div>
          <p className="text-xs text-ink-400">{job.stage || 'wird vorbereitet'} · {Math.round(job.progress * 100)} %</p>
        </div>
      )}

      {job?.status === 'failed' && <Banner kind="error">{job.error}</Banner>}

      {ready && scan.dimensions && (
        <Banner kind="success">
          Rekonstruktion fertig:{' '}
          <strong>
            {(scan.dimensions.width_mm as number).toFixed(1)} ×{' '}
            {(scan.dimensions.depth_mm as number).toFixed(1)} ×{' '}
            {(scan.dimensions.height_mm as number).toFixed(1)} mm
          </strong>
          {' '}aus {String(scan.dimensions.views)} Ansichten.
          <br />
          <span className="text-accent-300/80">
            Hinweis: Die Höhe kann bei flachen Oberseiten etwas zu groß ausfallen – das Verfahren
            umhüllt das Objekt. Die Tiefe der Tasche lässt sich danach frei einstellen.
          </span>
        </Banner>
      )}

      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn-ghost" onClick={onBack}>Zurück</button>
        <button type="button" className="btn-ghost flex-1" onClick={start}
                disabled={usable < 8 || Boolean(running)}>
          {running ? 'Berechnung läuft…' : usable < 8
            ? `Noch ${8 - usable} verwertbare Bilder nötig` : 'Berechnung starten'}
        </button>
        <button type="button" className="btn-primary flex-1" disabled={!ready} onClick={onUseMesh}>
          Als Aussparung verwenden
        </button>
      </div>
    </div>
  )
}
