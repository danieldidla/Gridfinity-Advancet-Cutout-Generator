export interface User { id: string; email: string; display_name: string; is_admin: boolean }

export interface ServerInfo {
  app_name: string
  allow_registration: boolean
  has_users: boolean
  max_upload_mb: number
  ai_segmentation: boolean
  reconstruction: boolean
}

export interface BinSettings {
  grid_x: number
  grid_y: number
  height_units: number
  wall_thickness: number
  floor_thickness: number
  solid: boolean
  stacking_lip: boolean
  lip_style: 'normal' | 'reduced' | 'none'
  lip_top_rim: number
  height_includes_lip: boolean
  lip_support: boolean
  magnet_holes: boolean
  magnet_diameter: number
  magnet_depth: number
  screw_holes: boolean
  screw_diameter: number
  screw_depth: number
  label_tab: boolean
  label_tab_width: number
  label_tab_angle: number
  corner_segments: number
}

export type Point = [number, number]

export interface CutoutSource { kind: 'image' | 'scan' | 'manual' | 'shape'; id: string | null; label: string }

export interface Cutout {
  id: string
  name: string
  enabled: boolean
  polygon: Point[]
  holes: Point[][]
  x: number
  y: number
  rotation: number
  depth: number
  clearance: number
  corner_radius: number
  draft_angle: number
  bottom_radius: number
  through: boolean
  finger_scoop: boolean
  finger_scoop_radius: number
  finger_notch: boolean
  finger_notch_diameter: number
  mesh_source: string | null
  mesh_open_top: boolean
  mesh_flip_z: boolean
  source: CutoutSource
}

export interface ProjectState {
  bin: BinSettings
  cutouts: Cutout[]
  view: { selected_cutout: string | null; camera: unknown | null; show_grid: boolean }
}

export interface ProjectSummary {
  id: string
  name: string
  revision: number
  created_at: string
  updated_at: string
  thumbnail: string | null
}

export interface ImageInfo {
  id: string
  filename: string
  width: number
  height: number
  paper: string
  corners: Point[] | null
  px_per_mm: number
  has_rectified: boolean
  trace: Record<string, number>
  note: string
  processed: boolean
  settings: TraceSettings | null
  created_at: string | null
}

export type TraceEngine = 'hybrid' | 'paper' | 'ai' | 'grabcut'

export interface TraceSettings {
  engine: TraceEngine
  sensitivity: number
  shadow_tolerance: number
  texture_suppression_mm: number
  neutral_objects: boolean
  illumination_order: number
  ai_threshold: number
  refine: boolean
  refine_band_mm: number
  close_mm: number
  open_mm: number
  fill_holes: boolean
  min_area_mm2: number
  smooth_mm: number
  simplify_mm: number
  include_holes: boolean
  min_hole_area_mm2: number
  keep_largest: boolean
  brush: number
}

export interface UploadResult {
  images: ImageInfo[]
  failed: { filename: string; reason: string }[]
}

export interface CoverageCell { sector: number; band: number; covered: boolean }
export interface Coverage {
  sectors: number
  bands: number
  band_labels: string[]
  cells: CoverageCell[]
  covered: number
  total: number
  ratio: number
}

export interface ScanInfo {
  id: string
  name: string
  status: 'capturing' | 'processing' | 'ready' | 'failed'
  coverage: Coverage | null
  dimensions: Record<string, number | string[]> | null
  message: string
  shot_count: number
  has_mesh: boolean
}

export interface ShotInfo {
  id: string
  sequence: number
  sharpness: number
  corner_count: number
  azimuth: number | null
  elevation: number | null
  usable: boolean
}

export interface Project extends ProjectSummary {
  state: ProjectState
  images: ImageInfo[]
  scans: ScanInfo[]
}

export interface ModelStats {
  triangles: number
  volume_mm3: number
  width_mm: number
  depth_mm: number
  height_mm: number
  material_cm3: number
  build_ms: number
  warnings: string[]
}

export interface TraceResult {
  polygon: Point[]
  holes: Point[][]
  width_mm: number
  height_mm: number
  area_mm2: number
  mask_preview: string | null
  engine_used: string
  took_ms: number
}

export interface Job {
  id: string
  kind: string
  status: 'queued' | 'running' | 'done' | 'failed'
  progress: number
  stage: string
  error: string | null
  result: Record<string, unknown> | null
}

export interface BoardInfo {
  squares_x: number
  squares_y: number
  square_mm: number
  width_mm: number
  height_mm: number
  azimuth_sectors: number
  elevation_bands: number[][]
  band_labels: string[]
  reconstruction_available: boolean
}
