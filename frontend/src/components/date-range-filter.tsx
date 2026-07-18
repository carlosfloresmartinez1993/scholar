import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

export type RangePreset = "dia" | "semana" | "catorcena" | "mes" | "custom";

export interface DateRange {
  preset: RangePreset;
  from: string; // YYYY-MM-DD inclusive
  to: string;
}

const PRESET_DAYS: Record<Exclude<RangePreset, "custom">, number> = {
  dia: 1,
  semana: 7,
  catorcena: 14,
  mes: 30,
};

function todayISO(): string {
  return new Date().toLocaleDateString("sv-SE");
}

function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + days);
  return d.toLocaleDateString("sv-SE");
}

/** Preset ranges END today and look back N-1 days (reports are historical). */
export function presetRange(preset: RangePreset): DateRange {
  const to = todayISO();
  if (preset === "custom") return { preset, from: addDays(to, -6), to };
  return { preset, from: addDays(to, -(PRESET_DAYS[preset] - 1)), to };
}

export function DateRangeFilter({
  value,
  onChange,
}: {
  value: DateRange;
  onChange: (r: DateRange) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Tabs
        value={value.preset}
        onValueChange={(v) => onChange(presetRange(v as RangePreset))}
      >
        <TabsList>
          <TabsTrigger value="dia">Hoy</TabsTrigger>
          <TabsTrigger value="semana">Semana</TabsTrigger>
          <TabsTrigger value="catorcena">Catorcena</TabsTrigger>
          <TabsTrigger value="mes">Mes</TabsTrigger>
          <TabsTrigger value="custom">Personalizado</TabsTrigger>
        </TabsList>
      </Tabs>
      {value.preset === "custom" && (
        <>
          <Input
            type="date"
            aria-label="Desde"
            className="w-40"
            value={value.from}
            onChange={(e) =>
              onChange({ ...value, from: e.target.value || value.from })
            }
          />
          <span className="text-muted-foreground">–</span>
          <Input
            type="date"
            aria-label="Hasta"
            className="w-40"
            value={value.to}
            min={value.from}
            onChange={(e) =>
              onChange({ ...value, to: e.target.value || value.to })
            }
          />
        </>
      )}
    </div>
  );
}
