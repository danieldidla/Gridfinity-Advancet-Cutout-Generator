import type { Coverage } from '../lib/types'

/**
 * The viewing hemisphere as a dartboard: one wedge per compass sector, one ring
 * per elevation band. Filled means we have a photo from there; the gaps are the
 * instruction.
 */
export default function CoverageWheel({ coverage, size = 200 }: {
  coverage: Coverage | null; size?: number
}) {
  if (!coverage) return null
  const { sectors, bands, cells } = coverage
  const centre = size / 2
  const outer = centre - 12
  const inner = outer * 0.28
  const ringWidth = (outer - inner) / bands

  return (
    <div className="flex flex-col items-center gap-2">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img"
           aria-label={`Abdeckung ${coverage.covered} von ${coverage.total} Bereichen`}>
        {cells.map(({ sector, band, covered }) => {
          // band 0 is the flattest angle and sits on the outside, because that
          // is where you physically stand when shooting low.
          const r0 = inner + (bands - 1 - band) * ringWidth
          const r1 = r0 + ringWidth - 1.5
          const a0 = (sector / sectors) * Math.PI * 2 - Math.PI / 2
          const a1 = ((sector + 1) / sectors) * Math.PI * 2 - Math.PI / 2
          return (
            <path
              key={`${sector}-${band}`}
              d={wedge(centre, centre, r0, r1, a0, a1)}
              className={covered
                ? 'fill-accent-500/85 stroke-ink-950'
                : 'fill-ink-800 stroke-ink-950'}
              strokeWidth={1}
            />
          )
        })}
        <circle cx={centre} cy={centre} r={inner - 3} className="fill-ink-900 stroke-ink-700" />
        <text x={centre} y={centre - 2} textAnchor="middle"
              className="fill-ink-100 text-[13px] font-semibold">
          {coverage.covered}/{coverage.total}
        </text>
        <text x={centre} y={centre + 11} textAnchor="middle" className="fill-ink-500 text-[9px]">
          Bereiche
        </text>
        {['N', 'O', 'S', 'W'].map((label, index) => {
          const angle = (index / 4) * Math.PI * 2 - Math.PI / 2
          return (
            <text key={label}
                  x={centre + Math.cos(angle) * (outer + 7)}
                  y={centre + Math.sin(angle) * (outer + 7) + 3}
                  textAnchor="middle" className="fill-ink-500 text-[9px]">{label}</text>
          )
        })}
      </svg>

      <ul className="space-y-0.5 text-[11px] text-ink-400">
        {coverage.band_labels?.map((label, index) => {
          const done = cells.filter((c) => c.band === index && c.covered).length
          return (
            <li key={label} className="flex items-center gap-2">
              <span className={`inline-block h-2 w-2 rounded-sm ${
                done === sectors ? 'bg-accent-500' : done > 0 ? 'bg-accent-800' : 'bg-ink-700'}`} />
              <span className="flex-1">{label}</span>
              <span className="font-mono">{done}/{sectors}</span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function wedge(cx: number, cy: number, r0: number, r1: number,
               a0: number, a1: number): string {
  const p = (r: number, a: number) => `${cx + Math.cos(a) * r} ${cy + Math.sin(a) * r}`
  const large = a1 - a0 > Math.PI ? 1 : 0
  return [
    `M ${p(r0, a0)}`,
    `L ${p(r1, a0)}`,
    `A ${r1} ${r1} 0 ${large} 1 ${p(r1, a1)}`,
    `L ${p(r0, a1)}`,
    `A ${r0} ${r0} 0 ${large} 0 ${p(r0, a0)}`,
    'Z',
  ].join(' ')
}
