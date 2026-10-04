import { create } from 'zustand'
import { api, ApiError } from './api'
import { defaultCutout, defaultState } from './defaults'
import type { BinSettings, Cutout, ImageInfo, Project, ProjectState, ScanInfo } from './types'

type SaveState = 'idle' | 'dirty' | 'saving' | 'saved' | 'error'

const HISTORY_LIMIT = 60
const AUTOSAVE_DELAY = 700

interface EditorStore {
  projectId: string | null
  name: string
  revision: number
  state: ProjectState
  images: ImageInfo[]
  scans: ScanInfo[]

  saveState: SaveState
  saveError: string | null
  loading: boolean
  loadError: string | null

  past: ProjectState[]
  future: ProjectState[]

  load: (id: string) => Promise<void>
  reset: () => void
  rename: (name: string) => void

  /** Every edit funnels through here so history and autosave stay consistent. */
  apply: (recipe: (draft: ProjectState) => void, options?: { history?: boolean }) => void
  commitHistory: () => void
  undo: () => void
  redo: () => void

  setBin: (patch: Partial<BinSettings>, history?: boolean) => void
  addCutout: (cutout?: Partial<Cutout>) => string
  updateCutout: (id: string, patch: Partial<Cutout>, history?: boolean) => void
  removeCutout: (id: string) => void
  duplicateCutout: (id: string) => void
  reorderCutout: (id: string, direction: -1 | 1) => void
  select: (id: string | null) => void

  setImages: (images: ImageInfo[]) => void
  setScans: (scans: ScanInfo[]) => void
  refreshScans: () => Promise<void>

  flush: () => Promise<void>
}

const clone = (value: ProjectState): ProjectState =>
  (typeof structuredClone === 'function'
    ? structuredClone(value)
    : JSON.parse(JSON.stringify(value)))

let saveTimer: ReturnType<typeof setTimeout> | null = null
/** Snapshot taken before a burst of edits, pushed onto the undo stack once. */
let pendingHistory: ProjectState | null = null

export const useEditor = create<EditorStore>((set, get) => {
  const scheduleSave = () => {
    if (saveTimer) clearTimeout(saveTimer)
    saveTimer = setTimeout(() => { void get().flush() }, AUTOSAVE_DELAY)
  }

  return {
    projectId: null,
    name: '',
    revision: 0,
    state: defaultState(),
    images: [],
    scans: [],
    saveState: 'idle',
    saveError: null,
    loading: false,
    loadError: null,
    past: [],
    future: [],

    reset: () => {
      if (saveTimer) clearTimeout(saveTimer)
      saveTimer = null
      pendingHistory = null
      set({
        projectId: null, name: '', revision: 0, state: defaultState(),
        images: [], scans: [], past: [], future: [],
        saveState: 'idle', saveError: null, loadError: null,
      })
    },

    load: async (id) => {
      set({ loading: true, loadError: null })
      try {
        const project: Project = await api.getProject(id)
        set({
          projectId: project.id,
          name: project.name,
          revision: project.revision,
          state: { ...defaultState(), ...project.state },
          images: project.images,
          scans: project.scans,
          past: [], future: [],
          saveState: 'idle', saveError: null, loading: false,
        })
      } catch (error) {
        set({
          loading: false,
          loadError: error instanceof Error ? error.message : 'Projekt konnte nicht geladen werden',
        })
      }
    },

    rename: (name) => {
      set({ name, saveState: 'dirty' })
      scheduleSave()
    },

    apply: (recipe, options) => {
      const { state, past } = get()
      const snapshot = clone(state)
      const next = clone(state)
      recipe(next)

      const keepHistory = options?.history ?? true
      let nextPast = past
      if (keepHistory) {
        nextPast = [...past, snapshot].slice(-HISTORY_LIMIT)
        pendingHistory = null
      } else if (pendingHistory === null) {
        // A drag or a slider produces a stream of updates; remember where it
        // started so undo steps over the whole gesture, not each frame.
        pendingHistory = snapshot
      }

      set({ state: next, past: nextPast, future: [], saveState: 'dirty' })
      scheduleSave()
    },

    commitHistory: () => {
      if (pendingHistory === null) return
      const { past } = get()
      set({ past: [...past, pendingHistory].slice(-HISTORY_LIMIT), future: [] })
      pendingHistory = null
    },

    undo: () => {
      get().commitHistory()
      const { past, future, state } = get()
      if (past.length === 0) return
      const previous = past[past.length - 1]
      set({
        state: previous,
        past: past.slice(0, -1),
        future: [clone(state), ...future].slice(0, HISTORY_LIMIT),
        saveState: 'dirty',
      })
      scheduleSave()
    },

    redo: () => {
      const { past, future, state } = get()
      if (future.length === 0) return
      set({
        state: future[0],
        past: [...past, clone(state)].slice(-HISTORY_LIMIT),
        future: future.slice(1),
        saveState: 'dirty',
      })
      scheduleSave()
    },

    setBin: (patch, history = true) =>
      get().apply((draft) => { Object.assign(draft.bin, patch) }, { history }),

    addCutout: (cutout) => {
      const created = defaultCutout(cutout)
      get().apply((draft) => {
        draft.cutouts.push(created)
        draft.view.selected_cutout = created.id
      })
      return created.id
    },

    updateCutout: (id, patch, history = true) =>
      get().apply((draft) => {
        const target = draft.cutouts.find((c) => c.id === id)
        if (target) Object.assign(target, patch)
      }, { history }),

    removeCutout: (id) =>
      get().apply((draft) => {
        draft.cutouts = draft.cutouts.filter((c) => c.id !== id)
        if (draft.view.selected_cutout === id) {
          draft.view.selected_cutout = draft.cutouts.at(-1)?.id ?? null
        }
      }),

    duplicateCutout: (id) =>
      get().apply((draft) => {
        const source = draft.cutouts.find((c) => c.id === id)
        if (!source) return
        const copy: Cutout = {
          ...clone({ ...defaultState(), cutouts: [source] }).cutouts[0],
          id: defaultCutout().id,
          name: `${source.name} (Kopie)`,
          x: source.x + 5,
          y: source.y - 5,
        }
        draft.cutouts.push(copy)
        draft.view.selected_cutout = copy.id
      }),

    reorderCutout: (id, direction) =>
      get().apply((draft) => {
        const index = draft.cutouts.findIndex((c) => c.id === id)
        const target = index + direction
        if (index < 0 || target < 0 || target >= draft.cutouts.length) return
        const [item] = draft.cutouts.splice(index, 1)
        draft.cutouts.splice(target, 0, item)
      }),

    select: (id) =>
      get().apply((draft) => { draft.view.selected_cutout = id }, { history: false }),

    setImages: (images) => set({ images }),
    setScans: (scans) => set({ scans }),

    refreshScans: async () => {
      const { projectId } = get()
      if (!projectId) return
      try {
        set({ scans: await api.listScans(projectId) })
      } catch {
        /* a failed poll is not worth surfacing; the next one may succeed */
      }
    },

    flush: async () => {
      const { projectId, state, name, revision, saveState } = get()
      if (!projectId || saveState === 'saving') return
      if (saveTimer) { clearTimeout(saveTimer); saveTimer = null }

      set({ saveState: 'saving', saveError: null })
      try {
        const saved = await api.saveProject(projectId, { name, state, revision })
        set({ revision: saved.revision, saveState: 'saved', saveError: null })
      } catch (error) {
        const conflict = error instanceof ApiError && error.status === 409
        set({
          saveState: 'error',
          saveError: conflict
            ? 'Das Projekt wurde in einem anderen Tab geändert. Seite neu laden, um den aktuellen Stand zu sehen.'
            : error instanceof Error ? error.message : 'Speichern fehlgeschlagen',
        })
      }
    },
  }
})

/** Persist immediately when the tab goes away, so nothing in flight is lost. */
if (typeof window !== 'undefined') {
  window.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') void useEditor.getState().flush()
  })
  window.addEventListener('pagehide', () => { void useEditor.getState().flush() })
}
