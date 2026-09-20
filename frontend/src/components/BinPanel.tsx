import { binSize, binTopZ, usableDepth } from '../lib/defaults'
import type { BinSettings } from '../lib/types'
import { IntField, NumberField, SelectField, Section, Toggle } from './ui'

interface Props {
  bin: BinSettings
  onChange: (patch: Partial<BinSettings>, final?: boolean) => void
}

export default function BinPanel({ bin, onChange }: Props) {
  const { width, depth } = binSize(bin)
  const top = binTopZ(bin)
  const lip = bin.stacking_lip && bin.lip_style !== 'none'

  return (
    <>
      <Section title="Raster & Größe">
        <div className="grid grid-cols-2 gap-2">
          <IntField label="Einheiten X" value={bin.grid_x}
                    onChange={(v) => onChange({ grid_x: v })} />
          <IntField label="Einheiten Y" value={bin.grid_y}
                    onChange={(v) => onChange({ grid_y: v })} />
        </div>
        <NumberField
          label="Höhe" value={bin.height_units} min={1} max={20} step={0.5} unit="u"
          onChange={(v, final) => onChange({ height_units: v }, final)}
          hint={`1 u = 7 mm Stapelraster · Außenmaß ${width.toFixed(1)} × ${depth.toFixed(1)} × ${(top + (lip ? 4.4 : 0)).toFixed(1)} mm`}
        />
        <div className="rounded-lg bg-ink-950/60 px-3 py-2 text-[11px] leading-relaxed text-ink-400">
          Innenraum bis Oberkante: <span className="font-mono text-ink-200">{top.toFixed(2)} mm</span><br />
          Maximale Cutout-Tiefe: <span className="font-mono text-ink-200">{usableDepth(bin).toFixed(2)} mm</span>
        </div>
      </Section>

      <Section title="Wände & Boden">
        <NumberField label="Wandstärke" value={bin.wall_thickness} min={0.4} max={6} step={0.1}
                     onChange={(v, f) => onChange({ wall_thickness: v }, f)}
                     hint="Vielfaches der Düsenbreite wählen, z. B. 1,2 mm bei 0,4 mm Düse." />
        <NumberField label="Bodenstärke" value={bin.floor_thickness} min={0.4} max={20} step={0.1}
                     onChange={(v, f) => onChange({ floor_thickness: v }, f)}
                     hint="Material über der Basis, bevor der Innenraum beginnt." />
        <Toggle
          label="Massiver Block" checked={bin.solid}
          onChange={(v) => onChange({ solid: v })}
          hint="Der Normalfall für Einlagen: Der Bin ist voll und nur die Aussparungen werden ausgeschnitten. Ausschalten ergibt einen gewöhnlichen hohlen Gridfinity-Behälter – dann wirken Aussparungen nur, wenn sie tiefer als der Innenboden reichen."
        />
      </Section>

      <Section title="Stapelrand">
        <Toggle label="Stapelrand" checked={bin.stacking_lip}
                onChange={(v) => onChange({ stacking_lip: v })}
                hint="Nimmt den Fuß eines aufgesetzten Bins auf." />
        <SelectField
          label="Ausführung" value={bin.lip_style}
          options={[
            { value: 'reduced', label: 'Abgeflacht (druckfreundlich)' },
            { value: 'normal', label: 'Original (scharfe Kante)' },
            { value: 'none', label: 'Ohne' },
          ]}
          onChange={(v) => onChange({ lip_style: v })}
          hint="Original läuft zur Kante hin auf 0,1 mm aus; abgeflacht lässt eine ebene Fläche stehen."
        />
        {bin.lip_style === 'reduced' && (
          <NumberField label="Breite der Randfläche" value={bin.lip_top_rim} min={0} max={2} step={0.05}
                       onChange={(v, f) => onChange({ lip_top_rim: v }, f)} disabled={!lip} />
        )}
        <Toggle label="Stützfase unter dem Rand" checked={bin.lip_support}
                onChange={(v) => onChange({ lip_support: v })} disabled={!lip || bin.solid}
                hint="45°-Übergang, damit die Auflage nicht frei in der Luft gedruckt wird." />
        <Toggle label="Höhe schließt den Rand ein" checked={bin.height_includes_lip}
                onChange={(v) => onChange({ height_includes_lip: v })} disabled={!lip}
                hint="Aus: 3 u ergibt 21 mm Stapelmaß plus 4,4 mm Rand. Ein: Gesamthöhe bleibt 21 mm." />
      </Section>

      <Section title="Unterseite" defaultOpen={false}>
        <Toggle label="Magnetlöcher (4 pro Zelle)" checked={bin.magnet_holes}
                onChange={(v) => onChange({ magnet_holes: v })} />
        {bin.magnet_holes && (
          <div className="grid grid-cols-2 gap-2">
            <NumberField label="Ø" value={bin.magnet_diameter} min={2} max={15} step={0.1}
                         onChange={(v, f) => onChange({ magnet_diameter: v }, f)} />
            <NumberField label="Tiefe" value={bin.magnet_depth} min={0.5} max={10} step={0.1}
                         onChange={(v, f) => onChange({ magnet_depth: v }, f)} />
          </div>
        )}
        <Toggle label="Schraublöcher" checked={bin.screw_holes}
                onChange={(v) => onChange({ screw_holes: v })} />
        {bin.screw_holes && (
          <div className="grid grid-cols-2 gap-2">
            <NumberField label="Ø" value={bin.screw_diameter} min={1} max={8} step={0.1}
                         onChange={(v, f) => onChange({ screw_diameter: v }, f)} />
            <NumberField label="Tiefe" value={bin.screw_depth} min={1} max={20} step={0.1}
                         onChange={(v, f) => onChange({ screw_depth: v }, f)} />
          </div>
        )}
      </Section>

      <Section title="Beschriftung & Qualität" defaultOpen={false}>
        <Toggle label="Beschriftungssteg" checked={bin.label_tab}
                onChange={(v) => onChange({ label_tab: v })}
                hint="Schräge Fläche an der hinteren Kante." />
        {bin.label_tab && (
          <div className="grid grid-cols-2 gap-2">
            <NumberField label="Breite" value={bin.label_tab_width} min={4} max={40} step={0.5}
                         onChange={(v, f) => onChange({ label_tab_width: v }, f)} />
            <NumberField label="Winkel" value={bin.label_tab_angle} min={10} max={75} step={1} unit="°"
                         onChange={(v, f) => onChange({ label_tab_angle: v }, f)} />
          </div>
        )}
        <NumberField label="Segmente je Rundung" value={bin.corner_segments} min={3} max={40} step={1} unit=""
                     onChange={(v, f) => onChange({ corner_segments: Math.round(v) }, f)}
                     hint="Höher = glattere Ecken, größere Datei." />
      </Section>
    </>
  )
}
