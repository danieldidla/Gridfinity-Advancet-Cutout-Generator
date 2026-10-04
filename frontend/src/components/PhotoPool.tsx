import { useRef, useState } from 'react'
import { api } from '../lib/api'
import type { ImageInfo } from '../lib/types'
import { Banner, Spinner } from './ui'

interface Props {
  projectId: string
  images: ImageInfo[]
  maxUploadMb: number
  onChanged: (images: ImageInfo[]) => void
  onProcess: (image: ImageInfo) => void
}

/**
 * The photographs, kept as a pool.
 *
 * Shooting and tracing are separate jobs and happen in separate places: the
 * phone takes the pictures, the desk draws the outlines. So this screen does
 * nothing but collect, and never asks for a decision that wants a mouse.
 */
export default function PhotoPool({
  projectId, images, maxUploadMb, onChanged, onProcess,
}: Props) {
  const [busy, setBusy] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [skipped, setSkipped] = useState<{ filename: string; reason: string }[]>([])
  const cameraRef = useRef<HTMLInputElement>(null)
  const filesRef = useRef<HTMLInputElement>(null)

  const upload = async (list: FileList) => {
    const files = Array.from(list)
    setBusy(files.length); setError(null); setSkipped([])
    try {
      const result = await api.uploadImages(projectId, files)
      onChanged([...images, ...result.images])
      if (result.failed.length) setSkipped(result.failed)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Hochladen fehlgeschlagen')
    } finally { setBusy(0) }
  }

  const remove = async (id: string) => {
    await api.deleteImage(projectId, id)
    onChanged(images.filter((i) => i.id !== id))
  }

  const setNote = async (image: ImageInfo, note: string) => {
    onChanged(images.map((i) => (i.id === image.id ? { ...i, note } : i)))
    try { await api.updateImage(projectId, image.id, { note }) } catch { /* retried on next edit */ }
  }

  const open = images.filter((i) => !i.processed).length

  return (
    <div className="space-y-4">
      <p className="text-sm leading-relaxed text-ink-300">
        Leg das Objekt auf ein leeres Blatt, sodass das ganze Blatt im Bild ist.
        Fotografiere möglichst senkrecht von oben. Du kannst beliebig viele Fotos
        sammeln und sie später in Ruhe am Rechner in Aussparungen verwandeln.
      </p>

      <div className="grid gap-2 sm:grid-cols-2">
        <button type="button" className="btn-primary" onClick={() => cameraRef.current?.click()}
                disabled={busy > 0}>
          📷 Fotos aufnehmen
        </button>
        <button type="button" className="btn-ghost" onClick={() => filesRef.current?.click()}
                disabled={busy > 0}>
          ⬆ Dateien hochladen
        </button>
      </div>
      <input ref={cameraRef} type="file" accept="image/*" capture="environment" multiple
             className="hidden"
             onChange={(e) => { if (e.target.files?.length) void upload(e.target.files); e.target.value = '' }} />
      <input ref={filesRef} type="file" accept="image/*" multiple className="hidden"
             onChange={(e) => { if (e.target.files?.length) void upload(e.target.files); e.target.value = '' }} />

      {busy > 0 && <Spinner label={`${busy} Foto(s) werden hochgeladen…`} />}
      {error && <Banner kind="error" onDismiss={() => setError(null)}>{error}</Banner>}
      {skipped.length > 0 && (
        <Banner kind="warn" onDismiss={() => setSkipped([])}>
          Nicht übernommen: {skipped.map((f) => `${f.filename} (${f.reason})`).join(', ')}.
          Maximal {maxUploadMb} MB je Datei.
        </Banner>
      )}

      {images.length === 0 ? (
        <p className="rounded-lg border border-dashed border-ink-700 px-4 py-8 text-center
                      text-xs text-ink-500">
          Noch keine Fotos. Vom Handy aufnehmen, später am Rechner weiterarbeiten.
        </p>
      ) : (
        <>
          <div className="flex items-baseline justify-between">
            <h3 className="label">{images.length} Foto(s), {open} offen</h3>
          </div>
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {images.map((image) => (
              <li key={image.id}
                  className={`group overflow-hidden rounded-lg border ${
                    image.processed ? 'border-ink-800 opacity-60' : 'border-ink-700'}`}>
                <button type="button" className="block w-full" onClick={() => onProcess(image)}>
                  <span className="relative block">
                    <img src={api.imageUrl(projectId, image.id)} alt={image.filename}
                         loading="lazy" className="aspect-[4/3] w-full object-cover" />
                    <span className={`absolute left-1 top-1 rounded px-1.5 py-0.5 text-[10px] ${
                      image.processed ? 'bg-accent-900/90 text-accent-200'
                        : image.has_rectified ? 'bg-ink-900/90 text-ink-200'
                        : 'bg-ink-900/90 text-ink-400'}`}>
                      {image.processed ? '✓ verarbeitet'
                        : image.has_rectified ? 'entzerrt' : 'neu'}
                    </span>
                    {image.corners === null && (
                      <span className="absolute right-1 top-1 rounded bg-amber-900/90 px-1.5
                                       py-0.5 text-[10px] text-amber-200" title="Blatt nicht automatisch erkannt">
                        Blatt?
                      </span>
                    )}
                  </span>
                </button>
                <div className="flex items-center gap-1 px-1.5 pb-1.5">
                  <input
                    className="min-w-0 flex-1 rounded bg-transparent px-1 py-0.5 text-[11px]
                               text-ink-300 outline-none placeholder:text-ink-600
                               hover:bg-ink-800/60 focus:bg-ink-800"
                    placeholder="Notiz…"
                    defaultValue={image.note}
                    onBlur={(e) => { if (e.target.value !== image.note) void setNote(image, e.target.value) }}
                  />
                  <button type="button" aria-label="Foto löschen"
                          className="shrink-0 px-1 text-xs text-ink-600 hover:text-red-400"
                          onClick={() => { void remove(image.id) }}>✕</button>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}

      <p className="text-[11px] leading-relaxed text-ink-500">
        Die Kamera-Schaltfläche verlangt HTTPS oder localhost – das ist eine Vorgabe der
        Browser. Ohne TLS die Fotos einfach hochladen.
      </p>
    </div>
  )
}
