import type { ServerInfo, TraceEngine, TraceSettings } from '../lib/types'
import { NumberField, SelectField, Section, Toggle } from './ui'

export const defaultTraceSettings = (): TraceSettings => ({
  engine: 'hybrid',
  sensitivity: 2.5,
  shadow_tolerance: 0.22,
  texture_suppression_mm: 1.2,
  neutral_objects: false,
  illumination_order: 2,
  ai_threshold: 0.5,
  refine: true,
  refine_band_mm: 2.5,
  close_mm: 0.8,
  open_mm: 0.5,
  fill_holes: false,
  min_area_mm2: 25,
  smooth_mm: 0,
  simplify_mm: 0.25,
  include_holes: true,
  min_hole_area_mm2: 4,
  keep_largest: true,
  brush: 10,
})

const ENGINES: { value: TraceEngine; label: string; hint: string }[] = [
  { value: 'hybrid', label: 'Hybrid (empfohlen)',
    hint: 'Papiermodell für die genaue Kante, KI als Rückfall für blasse Teile.' },
  { value: 'paper', label: 'Papiermodell',
    hint: 'Rechnet den Schatten heraus und ist am Rand am genauesten. Blind für neutrale graue Teile.' },
  { value: 'ai', label: 'Nur KI',
    hint: 'Findet fast alles, zieht aber Schatten mit und trifft die Kante nur grob.' },
  { value: 'grabcut', label: 'GrabCut (einfach)',
    hint: 'Das alte Verfahren, nur mit Rahmen. Als Notnagel.' },
]

export default function TracePanel({ settings, onChange, info }: {
  settings: TraceSettings
  onChange: (patch: Partial<TraceSettings>) => void
  info: ServerInfo | null
}) {
  const aiMissing = info ? !info.ai_segmentation : false
  const usesAi = settings.engine === 'ai' || settings.engine === 'hybrid'
  const usesPaper = settings.engine === 'paper' || settings.engine === 'hybrid'
  const chosen = ENGINES.find((e) => e.value === settings.engine)

  return (
    <div className="rounded-lg border border-ink-800 bg-ink-950/40">
      <Section title="Erkennung">
        <SelectField
          label="Verfahren" value={settings.engine}
          options={ENGINES.map((e) => ({ value: e.value, label: e.label }))}
          onChange={(v) => onChange({ engine: v })}
          hint={chosen?.hint}
        />
        {aiMissing && usesAi && (
          <p className="rounded border border-amber-800/60 bg-amber-950/40 px-2 py-1.5
                        text-[11px] text-amber-200">
            Kein Erkennungsmodell installiert – es wird automatisch das Papiermodell
            verwendet. Nachrüsten: <code>bash deploy/fetch-models.sh</code>
          </p>
        )}

        {usesPaper && (
          <>
            <NumberField
              label="Empfindlichkeit" value={settings.sensitivity} min={1} max={10} step={0.1}
              unit="×" onChange={(v) => onChange({ sensitivity: v })}
              hint="Vielfaches des Papierrauschens. Kleiner = findet mehr, nimmt aber eher Papierstruktur mit."
            />
            <NumberField
              label="Schattentoleranz" value={settings.shadow_tolerance} min={0} max={0.9} step={0.01}
              unit="" onChange={(v) => onChange({ shadow_tolerance: v })}
              hint="Ab welcher Dunkelheit etwas als Objekt gilt, egal wie neutral es ist. Höher holt dunkle Teile, zieht aber Schatten mit."
            />
            <NumberField
              label="Papierstruktur glätten" value={settings.texture_suppression_mm}
              min={0} max={6} step={0.1} onChange={(v) => onChange({ texture_suppression_mm: v })}
              hint="Entfernt Karo- und Linienraster. Etwas größer als die Linienbreite wählen."
            />
            <Toggle
              label="Neutrale graue Teile mitnehmen" checked={settings.neutral_objects}
              onChange={(v) => onChange({ neutral_objects: v })}
              hint="Hilft bei blassen Teilen ohne Farbe – holt dann aber leichter Schatten herein. Mit „Hybrid“ meist unnötig."
            />
          </>
        )}

        {usesAi && !aiMissing && (
          <NumberField
            label="KI-Schwelle" value={settings.ai_threshold} min={0.05} max={0.95} step={0.05}
            unit="" onChange={(v) => onChange({ ai_threshold: v })}
            hint="Niedriger = großzügiger."
          />
        )}
      </Section>

      <Section title="Kante & Aufräumen" defaultOpen={false}>
        <Toggle
          label="Grobe Kante nachschärfen" checked={settings.refine}
          onChange={(v) => onChange({ refine: v })}
          hint="Wirkt nur, wenn die Kontur vom Modell kam – das Papiermodell trifft die Kante ohnehin genauer, als Nachschärfen es könnte."
        />
        {settings.refine && (
          <NumberField label="Suchbreite" value={settings.refine_band_mm} min={0.5} max={8} step={0.1}
                       onChange={(v) => onChange({ refine_band_mm: v })} />
        )}
        <NumberField label="Lücken schließen" value={settings.close_mm} min={0} max={5} step={0.1}
                     onChange={(v) => onChange({ close_mm: v })} />
        <NumberField label="Flecken entfernen" value={settings.open_mm} min={0} max={5} step={0.1}
                     onChange={(v) => onChange({ open_mm: v })} />
        <NumberField label="Kleinste Fläche" value={settings.min_area_mm2} min={0} max={2000} step={5}
                     unit="mm²" onChange={(v) => onChange({ min_area_mm2: v })}
                     hint="Alles Kleinere gilt als Störung." />
        <Toggle label="Innenlöcher schließen" checked={settings.fill_holes}
                onChange={(v) => onChange({ fill_holes: v })}
                hint="Für Teile, die innen Durchbrüche haben, die du nicht aussparen willst." />
      </Section>

      <Section title="Kontur" defaultOpen={false}>
        <NumberField label="Vereinfachen" value={settings.simplify_mm} min={0} max={3} step={0.05}
                     onChange={(v) => onChange({ simplify_mm: v })}
                     hint="Höher = weniger Punkte, gröbere Kontur." />
        <NumberField label="Glätten" value={settings.smooth_mm} min={0} max={4} step={0.1}
                     onChange={(v) => onChange({ smooth_mm: v })}
                     hint="Bügelt ausgefranste Ränder aus." />
        <Toggle label="Innenlöcher übernehmen" checked={settings.include_holes}
                onChange={(v) => onChange({ include_holes: v })} />
        {settings.include_holes && (
          <NumberField label="Kleinstes Loch" value={settings.min_hole_area_mm2} min={0} max={500}
                       step={1} unit="mm²" onChange={(v) => onChange({ min_hole_area_mm2: v })} />
        )}
      </Section>
    </div>
  )
}
