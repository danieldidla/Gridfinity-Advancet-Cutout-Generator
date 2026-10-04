import type { BinSettings, Cutout, Point, ProjectState } from './types'

export const GRID_PITCH = 42
export const BIN_CLEARANCE = 0.5
export const HEIGHT_UNIT = 7
export const BASE_HEIGHT = 4.75
export const LIP_HEIGHT = 4.4

export const defaultBin = (): BinSettings => ({
  grid_x: 2,
  grid_y: 2,
  height_units: 3,
  wall_thickness: 1.2,
  floor_thickness: 1.4,
  solid: true,
  stacking_lip: true,
  lip_style: 'reduced',
  lip_top_rim: 0.6,
  height_includes_lip: false,
  lip_support: true,
  magnet_holes: false,
  magnet_diameter: 6.5,
  magnet_depth: 2.4,
  screw_holes: false,
  screw_diameter: 3,
  screw_depth: 6,
  label_tab: false,
  label_tab_width: 12,
  label_tab_angle: 36,
  corner_segments: 12,
})

export const defaultState = (): ProjectState => ({
  bin: defaultBin(),
  cutouts: [],
  view: { selected_cutout: null, camera: null, show_grid: true },
})

export const newId = (): string =>
  (crypto.randomUUID?.() ?? Math.random().toString(16).slice(2)).replace(/-/g, '').slice(0, 12)

export const defaultCutout = (overrides: Partial<Cutout> = {}): Cutout => ({
  id: newId(),
  name: 'Cutout',
  enabled: true,
  polygon: [],
  holes: [],
  x: 0,
  y: 0,
  rotation: 0,
  depth: 10,
  clearance: 0.4,
  corner_radius: 0,
  draft_angle: 0,
  bottom_radius: 0,
  through: false,
  finger_scoop: false,
  finger_scoop_radius: 8,
  finger_notch: false,
  finger_notch_diameter: 18,
  mesh_source: null,
  mesh_open_top: true,
  mesh_flip_z: true,
  source: { kind: 'manual', id: null, label: '' },
  ...overrides,
})

/** Outer footprint of the bin in millimetres. */
export const binSize = (bin: BinSettings): { width: number; depth: number } => ({
  width: bin.grid_x * GRID_PITCH - BIN_CLEARANCE,
  depth: bin.grid_y * GRID_PITCH - BIN_CLEARANCE,
})

export const binTopZ = (bin: BinSettings): number => {
  const pitch = bin.height_units * HEIGHT_UNIT
  const lip = bin.stacking_lip && bin.lip_style !== 'none' ? LIP_HEIGHT : 0
  return bin.height_includes_lip ? pitch - lip : pitch
}

/** How deep a pocket can go before it breaks through the floor. */
export const usableDepth = (bin: BinSettings): number =>
  Math.max(0, binTopZ(bin) - (BASE_HEIGHT + bin.floor_thickness))

export const rectanglePolygon = (width: number, height: number): Point[] => [
  [-width / 2, -height / 2], [width / 2, -height / 2],
  [width / 2, height / 2], [-width / 2, height / 2],
]

export const circlePolygon = (diameter: number, segments = 64): Point[] =>
  Array.from({ length: segments }, (_, i) => {
    const angle = (i / segments) * Math.PI * 2
    return [Math.cos(angle) * diameter / 2, Math.sin(angle) * diameter / 2] as Point
  })

export const polygonBounds = (points: Point[]) => {
  if (points.length === 0) return { minX: 0, minY: 0, maxX: 0, maxY: 0, width: 0, height: 0 }
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const [x, y] of points) {
    if (x < minX) minX = x
    if (x > maxX) maxX = x
    if (y < minY) minY = y
    if (y > maxY) maxY = y
  }
  return { minX, minY, maxX, maxY, width: maxX - minX, height: maxY - minY }
}

/** Rotate a point about the origin, in degrees. */
export const rotatePoint = ([x, y]: Point, degrees: number): Point => {
  const a = (degrees * Math.PI) / 180
  const c = Math.cos(a), s = Math.sin(a)
  return [x * c - y * s, x * s + y * c]
}
