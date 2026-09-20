import { polygonBounds, usableDepth } from '../lib/defaults'
import type { BinSettings, Cutout } from '../lib/types'
import { Banner, NumberField, Section, Toggle } from './ui'

interface Props {
  cutout: Cutout
  bin: BinSettings
  onChange: (patch: Partial<Cutout>, final?: boolean) => void
}

export default function CutoutPanel({ cutout, bin, onChange }: Props) {
  const bounds = polygonBounds(cutout.polygon)
  const maxDepth = usableDepth(bin)
  const tooDeep = !cutout.through && cutout.depth > maxDepth + 1e-6
  const isMesh = Boolean(cutout.mesh_source)
  const halfWidth = (bin.grid_x * 42 - 0.5) / 2
  const halfDepth = (bin.grid_y * 42 - 0.5) / 2

  return (
    <>
      <Section title="Aussparung">
        <div>
          <label className="label mb-1">Name</label>
          <input className="field" value={cutout.name} maxLength={80}
                 onChange={(e) => onChange({ name: e.target.value })} />
        </div>
        <Toggle label="Aktiv" checked={cutout.enabled}
                onChange={(v) => onChange({ enabled: v })}
                hint="Inaktive Aussparungen bleiben erhalten, werden aber nicht ausgeschnitten." />
        <div className="rounded-lg bg-ink-950/60 px-3 py-2 text-[11px] leading-relaxed text-ink-400">
          {isMesh ? (
            <>Quelle: <span className="text-ink-200">3D-Aufnahme</span><br />
              Form kommt aus dem gescannten Netz.</>
          ) : (
            <>Kontur: <span className="font-mono text-ink-200">{cutout.polygon.length}</span> Punkte
              {cutout.holes.length > 0 && <>, <span className="font-mono text-ink-200">{cutout.holes.length}</span> Löcher</>}
              <br />
              Maß: <span className="font-mono text-ink-200">
                {bounds.width.toFixed(1)} × {bounds.height.toFixed(1)} mm
              </span></>
          )}
        </div>
      </Section>

      <Section title="Position">
        <div className="grid grid-cols-2 gap-2">
          <NumberField label="X" value={cutout.x} min={-halfWidth} max={halfWidth} step={0.1}
                       onChange={(v, f) => onChange({ x: v }, f)} />
          <NumberField label="Y" value={cutout.y} min={-halfDepth} max={halfDepth} step={0.1}
                       onChange={(v, f) => onChange({ y: v }, f)} />
        </div>
        <NumberField label="Drehung" value={cutout.rotation} min={0} max={360} step={1} unit="°"
                     onChange={(v, f) => onChange({ rotation: v }, f)} />
        <div className="flex gap-2">
          <button type="button" className="btn-ghost btn-sm flex-1"
                  onClick={() => onChange({ x: 0, y: 0 }, true)}>Zentrieren</button>
          <button type="button" className="btn-ghost btn-sm flex-1"
                  onClick={() => onChange({ rotation: 0 }, true)}>Drehung 0°</button>
        </div>
      </Section>

      <Section title="Tiefe & Passung">
        <NumberField
          label="Tiefe" value={cutout.depth} min={0.2} max={Math.max(40, maxDepth)} step={0.1}
          onChange={(v, f) => onChange({ depth: v }, f)} disabled={cutout.through}
          hint={`Gemessen von der Oberkante nach unten. Maximal ${maxDepth.toFixed(1)} mm ohne Durchbruch.`}
        />
        {tooDeep && (
          <Banner kind="warn">
            Die Tiefe geht durch den Boden. Entweder die Bin-Höhe erhöhen oder „Durchbruch“ aktivieren.
          </Banner>
        )}
        <Toggle label="Durchbruch" checked={cutout.through}
                onChange={(v) => onChange({ through: v })}
                hint="Schneidet komplett durch den Boden." />
        <NumberField
          label="Spiel (Clearance)" value={cutout.clearance} min={-2} max={5} step={0.05}
          onChange={(v, f) => onChange({ clearance: v }, f)}
          hint="Wird ringsum auf die Kontur addiert. 0,3–0,6 mm passen für die meisten Drucker."
        />
      </Section>

      <Section title="Form" defaultOpen={!isMesh}>
        {isMesh ? (
          <>
            <Toggle
              label="Nach oben öffnen" checked={cutout.mesh_open_top}
              onChange={(v) => onChange({ mesh_open_top: v })}
              hint="Entfernt Hinterschnitte, damit das Teil von oben eingelegt werden kann. Ohne diese Option bleibt die Tasche unter Umständen unbenutzbar."
            />
            <Toggle
              label="Objekt lag kopfüber" checked={cutout.mesh_flip_z}
              onChange={(v) => onChange({ mesh_flip_z: v })}
              hint="So sieht es die Anleitung vor: Die gescannte Unterseite wird zum Taschenboden. Nur abschalten, wenn das Objekt aufrecht fotografiert wurde."
            />
          </>
        ) : (
          <>
            <NumberField label="Eckenradius" value={cutout.corner_radius} min={0} max={20} step={0.1}
                         onChange={(v, f) => onChange({ corner_radius: v }, f)}
                         hint="Rundet die Kontur in der Draufsicht." />
            <NumberField label="Entformschräge" value={cutout.draft_angle} min={0} max={30} step={0.5} unit="°"
                         onChange={(v, f) => onChange({ draft_angle: v }, f)}
                         hint="Erweitert die Tasche nach oben – das Teil lässt sich leichter entnehmen." />
            <NumberField label="Bodenradius" value={cutout.bottom_radius} min={0} max={10} step={0.1}
                         onChange={(v, f) => onChange({ bottom_radius: v }, f)}
                         hint="Verrundet den Übergang von Wand zu Taschenboden." />
          </>
        )}
      </Section>

      <Section title="Entnahmehilfen" defaultOpen={false}>
        <Toggle label="Griffmulde (Rampe)" checked={cutout.finger_scoop}
                onChange={(v) => onChange({ finger_scoop: v })}
                hint="Material-Rampe an der vorderen Taschenkante zum Herausschieben." />
        {cutout.finger_scoop && (
          <NumberField label="Radius" value={cutout.finger_scoop_radius} min={1} max={30} step={0.5}
                       onChange={(v, f) => onChange({ finger_scoop_radius: v }, f)} />
        )}
        <Toggle label="Fingerausschnitt" checked={cutout.finger_notch}
                onChange={(v) => onChange({ finger_notch: v })}
                hint="Halbrunder Ausschnitt in der Taschenwand, um das Teil zu greifen." />
        {cutout.finger_notch && (
          <NumberField label="Durchmesser" value={cutout.finger_notch_diameter} min={2} max={60} step={0.5}
                       onChange={(v, f) => onChange({ finger_notch_diameter: v }, f)} />
        )}
      </Section>
    </>
  )
}
