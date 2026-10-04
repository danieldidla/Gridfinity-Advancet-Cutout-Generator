import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { GRID_PITCH, binSize, polygonBounds, rotatePoint } from '../lib/defaults'
import type { BinSettings, Cutout, Point } from '../lib/types'

interface Props {
  bin: BinSettings
  cutouts: Cutout[]
  selectedId: string | null
  onSelect: (id: string | null) => void
  onMove: (id: string, x: number, y: number, final: boolean) => void
  onRotate: (id: string, rotation: number, final: boolean) => void
}

const MARGIN = 14      // millimetres of breathing room around the bin
const HANDLE_MM = 9

type Drag =
  | { mode: 'move'; id: string; offsetX: number; offsetY: number }
  | { mode: 'rotate'; id: string; startAngle: number; startRotation: number }

/** Top-down plan view: drag to place a cutout, drag the handle to spin it. */
export default function LayoutEditor({
  bin, cutouts, selectedId, onSelect, onMove, onRotate,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [drag, setDrag] = useState<Drag | null>(null)
  const [snap, setSnap] = useState(true)

  const { width, depth } = binSize(bin)
  const viewBox = useMemo(
    () => `${-width / 2 - MARGIN} ${-depth / 2 - MARGIN} ${width + MARGIN * 2} ${depth + MARGIN * 2}`,
    [width, depth],
  )

  /** Convert a pointer event to millimetres in bin space (y flipped). */
  const toMillimetres = useCallback((event: React.PointerEvent | PointerEvent): Point => {
    const svg = svgRef.current
    if (!svg) return [0, 0]
    const rect = svg.getBoundingClientRect()
    const vx = -width / 2 - MARGIN
    const vy = -depth / 2 - MARGIN
    const vw = width + MARGIN * 2
    const vh = depth + MARGIN * 2
    // preserveAspectRatio="xMidYMid meet" letterboxes the viewBox
    const scale = Math.min(rect.width / vw, rect.height / vh)
    const offsetX = (rect.width - vw * scale) / 2
    const offsetY = (rect.height - vh * scale) / 2
    const x = (event.clientX - rect.left - offsetX) / scale + vx
    const y = (event.clientY - rect.top - offsetY) / scale + vy
    return [x, -y]
  }, [width, depth])

  const beginMove = (event: React.PointerEvent, cutout: Cutout) => {
    event.stopPropagation()
    ;(event.target as Element).setPointerCapture?.(event.pointerId)
    const [mx, my] = toMillimetres(event)
    onSelect(cutout.id)
    setDrag({ mode: 'move', id: cutout.id, offsetX: mx - cutout.x, offsetY: my - cutout.y })
  }

  const beginRotate = (event: React.PointerEvent, cutout: Cutout) => {
    event.stopPropagation()
    ;(event.target as Element).setPointerCapture?.(event.pointerId)
    const [mx, my] = toMillimetres(event)
    const angle = (Math.atan2(my - cutout.y, mx - cutout.x) * 180) / Math.PI
    setDrag({ mode: 'rotate', id: cutout.id, startAngle: angle, startRotation: cutout.rotation })
  }

  useEffect(() => {
    if (!drag) return

    const step = (event: PointerEvent, final: boolean) => {
      const [mx, my] = toMillimetres(event)
      if (drag.mode === 'move') {
        let x = mx - drag.offsetX
        let y = my - drag.offsetY
        if (snap && !event.altKey) {
          // Snap to the centres of the grid cells, which is where a single
          // cutout usually wants to sit.
          const cellX = GRID_PITCH, cellY = GRID_PITCH
          const originX = (-(bin.grid_x - 1) * cellX) / 2
          const originY = (-(bin.grid_y - 1) * cellY) / 2
          const nearestX = originX + Math.round((x - originX) / cellX) * cellX
          const nearestY = originY + Math.round((y - originY) / cellY) * cellY
          if (Math.abs(nearestX - x) < 3) x = nearestX
          if (Math.abs(nearestY - y) < 3) y = nearestY
        }
        onMove(drag.id, round(x), round(y), final)
      } else {
        const angle = (Math.atan2(my - currentY(drag.id), mx - currentX(drag.id)) * 180) / Math.PI
        let rotation = drag.startRotation + (angle - drag.startAngle)
        if (snap && !event.altKey) {
          const nearest = Math.round(rotation / 15) * 15
          if (Math.abs(nearest - rotation) < 4) rotation = nearest
        }
        onRotate(drag.id, round(((rotation % 360) + 360) % 360), final)
      }
    }

    const currentX = (id: string) => cutouts.find((c) => c.id === id)?.x ?? 0
    const currentY = (id: string) => cutouts.find((c) => c.id === id)?.y ?? 0

    const onPointerMove = (event: PointerEvent) => step(event, false)
    const onPointerUp = (event: PointerEvent) => { step(event, true); setDrag(null) }

    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', onPointerUp)
    window.addEventListener('pointercancel', onPointerUp)
    return () => {
      window.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('pointerup', onPointerUp)
      window.removeEventListener('pointercancel', onPointerUp)
    }
  }, [drag, snap, toMillimetres, onMove, onRotate, cutouts, bin.grid_x, bin.grid_y])

  return (
    <div className="relative h-full w-full">
      <svg
        ref={svgRef}
        viewBox={viewBox}
        preserveAspectRatio="xMidYMid meet"
        className="h-full w-full touch-none"
        onPointerDown={() => onSelect(null)}
      >
        {/* bin outline */}
        <rect
          x={-width / 2} y={-depth / 2} width={width} height={depth} rx={4}
          className="fill-ink-900 stroke-ink-600" strokeWidth={0.5}
        />
        {/* grid cells */}
        {Array.from({ length: bin.grid_x }, (_, ix) =>
          Array.from({ length: bin.grid_y }, (_, iy) => {
            const cx = (ix - (bin.grid_x - 1) / 2) * GRID_PITCH
            const cy = (iy - (bin.grid_y - 1) / 2) * GRID_PITCH
            return (
              <g key={`${ix}-${iy}`}>
                <rect
                  x={cx - GRID_PITCH / 2 + 0.25} y={-cy - GRID_PITCH / 2 + 0.25}
                  width={GRID_PITCH - 0.5} height={GRID_PITCH - 0.5}
                  className="fill-none stroke-ink-700" strokeWidth={0.35}
                  strokeDasharray="2 2"
                />
                <circle cx={cx} cy={-cy} r={0.6} className="fill-ink-600" />
              </g>
            )
          }))}

        {cutouts.map((cutout) => {
          if (cutout.polygon.length < 3) return null
          const selected = cutout.id === selectedId
          const transform = `translate(${cutout.x} ${-cutout.y}) rotate(${-cutout.rotation})`
          return (
            <g key={cutout.id} transform={transform} opacity={cutout.enabled ? 1 : 0.32}>
              <path
                d={toPath(cutout.polygon, cutout.holes)}
                fillRule="evenodd"
                className={selected
                  ? 'fill-accent-500/40 stroke-accent-300'
                  : 'fill-ink-700/60 stroke-ink-400 hover:fill-ink-600/70'}
                strokeWidth={selected ? 0.7 : 0.45}
                style={{ cursor: drag ? 'grabbing' : 'grab' }}
                onPointerDown={(event) => beginMove(event, cutout)}
              />
              {selected && <RotateHandle cutout={cutout} onPointerDown={beginRotate} />}
            </g>
          )
        })}
      </svg>

      <label className="absolute bottom-2 left-2 flex items-center gap-2 rounded-lg
                        bg-ink-900/85 px-2 py-1 text-xs text-ink-300">
        <input type="checkbox" checked={snap} onChange={(e) => setSnap(e.target.checked)}
               className="accent-accent-500" />
        Einrasten <span className="text-ink-500">(Alt hält frei)</span>
      </label>
    </div>
  )
}

function RotateHandle({ cutout, onPointerDown }: {
  cutout: Cutout
  onPointerDown: (event: React.PointerEvent, cutout: Cutout) => void
}) {
  const bounds = polygonBounds(cutout.polygon)
  const y = bounds.maxY + HANDLE_MM
  return (
    <g>
      <line x1={0} y1={-bounds.maxY} x2={0} y2={-y}
            className="stroke-accent-300" strokeWidth={0.4} strokeDasharray="1.5 1.5" />
      <circle
        cx={0} cy={-y} r={2.6}
        className="fill-accent-400 stroke-ink-950"
        strokeWidth={0.5}
        style={{ cursor: 'alias' }}
        onPointerDown={(event) => onPointerDown(event, cutout)}
      />
    </g>
  )
}

function toPath(polygon: Point[], holes: Point[][]): string {
  const ring = (points: Point[]) =>
    points.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(3)},${(-y).toFixed(3)}`).join(' ') + ' Z'
  return [ring(polygon), ...holes.filter((h) => h.length >= 3).map(ring)].join(' ')
}

const round = (value: number) => Math.round(value * 100) / 100

export { rotatePoint }
