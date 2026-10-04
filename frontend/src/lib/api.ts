import type {
  BoardInfo, Coverage, ImageInfo, Job, ModelStats, Project, ProjectState,
  ProjectSummary, ScanInfo, ServerInfo, ShotInfo, TraceResult, User,
} from './types'

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    credentials: 'same-origin',
    ...init,
    headers: {
      ...(init.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(init.headers ?? {}),
    },
  })
  if (!response.ok) throw new ApiError(response.status, await errorText(response))
  if (response.status === 204) return undefined as T
  const type = response.headers.get('content-type') ?? ''
  if (type.includes('application/json')) return response.json() as Promise<T>
  return response.blob() as Promise<T>
}

async function errorText(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body.detail === 'string') return body.detail
    if (Array.isArray(body.detail)) {
      return body.detail.map((d: { msg?: string }) => d.msg ?? '').join('; ')
    }
  } catch {
    /* fall through to the status text */
  }
  return response.statusText || `Fehler ${response.status}`
}

const json = (body: unknown): RequestInit => ({ body: JSON.stringify(body) })

export const api = {
  info: () => request<ServerInfo>('/api/auth/info'),
  me: () => request<User>('/api/auth/me'),
  login: (email: string, password: string) =>
    request<User>('/api/auth/login', { method: 'POST', ...json({ email, password }) }),
  register: (email: string, password: string, display_name: string) =>
    request<User>('/api/auth/register', { method: 'POST', ...json({ email, password, display_name }) }),
  logout: () => request<void>('/api/auth/logout', { method: 'POST' }),

  listProjects: () => request<ProjectSummary[]>('/api/projects'),
  createProject: (name: string) =>
    request<Project>('/api/projects', { method: 'POST', ...json({ name }) }),
  getProject: (id: string) => request<Project>(`/api/projects/${id}`),
  saveProject: (id: string, payload: { name?: string; state?: ProjectState; revision?: number }) =>
    request<ProjectSummary>(`/api/projects/${id}`, { method: 'PATCH', ...json(payload) }),
  duplicateProject: (id: string) =>
    request<Project>(`/api/projects/${id}/duplicate`, { method: 'POST' }),
  deleteProject: (id: string) => request<void>(`/api/projects/${id}`, { method: 'DELETE' }),
  setThumbnail: (id: string, dataUrl: string) =>
    request<void>(`/api/projects/${id}/thumbnail`, { method: 'PUT', ...json({ data_url: dataUrl }) }),

  uploadImage: (projectId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<ImageInfo>(`/api/projects/${projectId}/images`, { method: 'POST', body: form })
  },
  imageUrl: (projectId: string, imageId: string, rectified = false) =>
    `/api/projects/${projectId}/images/${imageId}/file?rectified=${rectified}`,
  detectSheet: (projectId: string, imageId: string) =>
    request<ImageInfo>(`/api/projects/${projectId}/images/${imageId}/detect`, { method: 'POST' }),
  rectify: (projectId: string, imageId: string, body: unknown) =>
    request<ImageInfo>(`/api/projects/${projectId}/images/${imageId}/rectify`, { method: 'POST', ...json(body) }),
  trace: (projectId: string, imageId: string, body: unknown) =>
    request<TraceResult>(`/api/projects/${projectId}/images/${imageId}/trace`, { method: 'POST', ...json(body) }),
  deleteImage: (projectId: string, imageId: string) =>
    request<void>(`/api/projects/${projectId}/images/${imageId}`, { method: 'DELETE' }),

  boardInfo: () => request<BoardInfo>('/api/scan-board/info'),
  createScan: (projectId: string, name: string) =>
    request<ScanInfo>(`/api/projects/${projectId}/scans`, { method: 'POST', ...json({ name }) }),
  listScans: (projectId: string) => request<ScanInfo[]>(`/api/projects/${projectId}/scans`),
  getScan: (projectId: string, scanId: string) =>
    request<ScanInfo>(`/api/projects/${projectId}/scans/${scanId}`),
  listShots: (projectId: string, scanId: string) =>
    request<ShotInfo[]>(`/api/projects/${projectId}/scans/${scanId}/shots`),
  addShot: (projectId: string, scanId: string, file: Blob) => {
    const form = new FormData()
    form.append('file', file, 'shot.jpg')
    return request<{ shot: ShotInfo; hint: string; coverage: Coverage }>(
      `/api/projects/${projectId}/scans/${scanId}/shots`, { method: 'POST', body: form })
  },
  deleteShot: (projectId: string, scanId: string, shotId: string) =>
    request<void>(`/api/projects/${projectId}/scans/${scanId}/shots/${shotId}`, { method: 'DELETE' }),
  shotUrl: (projectId: string, scanId: string, shotId: string) =>
    `/api/projects/${projectId}/scans/${scanId}/shots/${shotId}/file`,
  reconstruct: (projectId: string, scanId: string, settings?: unknown) =>
    request<Job>(`/api/projects/${projectId}/scans/${scanId}/reconstruct`,
      { method: 'POST', ...json(settings ?? null) }),
  deleteScan: (projectId: string, scanId: string) =>
    request<void>(`/api/projects/${projectId}/scans/${scanId}`, { method: 'DELETE' }),

  job: (id: string) => request<Job>(`/api/jobs/${id}`),

  stats: (body: unknown) =>
    request<ModelStats>('/api/geometry/stats', { method: 'POST', ...json(body) }),

  adminUsers: () => request<User[]>('/api/admin/users'),
  adminCreateUser: (email: string, password: string, display_name: string) =>
    request<User>('/api/admin/users', { method: 'POST', ...json({ email, password, display_name }) }),
  adminUpdateUser: (id: string, patch: Record<string, unknown>) =>
    request<User>(`/api/admin/users/${id}`, { method: 'PATCH', ...json(patch) }),
  adminDeleteUser: (id: string) => request<void>(`/api/admin/users/${id}`, { method: 'DELETE' }),
  adminStats: () => request<Record<string, number>>('/api/admin/stats'),
}

/** Fetches a preview mesh, using the ETag so an unchanged model costs nothing. */
export async function fetchPreview(
  body: unknown, etag: string | null, signal?: AbortSignal,
): Promise<{ buffer: ArrayBuffer | null; etag: string | null }> {
  const response = await fetch('/api/geometry/preview.glb', {
    method: 'POST',
    credentials: 'same-origin',
    signal,
    headers: {
      'Content-Type': 'application/json',
      ...(etag ? { 'If-None-Match': etag } : {}),
    },
    body: JSON.stringify(body),
  })
  if (response.status === 304) return { buffer: null, etag }
  if (!response.ok) throw new ApiError(response.status, await errorText(response))
  return { buffer: await response.arrayBuffer(), etag: response.headers.get('etag') }
}

export async function downloadExport(
  format: 'stl' | '3mf', body: unknown, name: string,
): Promise<void> {
  const response = await fetch(
    `/api/geometry/export.${format}?name=${encodeURIComponent(name)}`,
    {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  if (!response.ok) throw new ApiError(response.status, await errorText(response))

  const blob = await response.blob()
  const disposition = response.headers.get('content-disposition') ?? ''
  const match = /filename="([^"]+)"/.exec(disposition)
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = match?.[1] ?? `modell.${format}`
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
