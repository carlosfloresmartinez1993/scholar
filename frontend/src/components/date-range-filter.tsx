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

/** Preset ranges start TODAY (not the selected term/nómina). */
export function presetRange(preset: RangePreset): DateRange {
  const from = todayISO();
  if (preset === "custom") return { preset, from, to: addDays(from, 6) };
  return { preset, from, to: addDays(from, PRESET_DAYS[preset] - 1) };
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

/** Dates in [from, to] falling on `weekday` (0=Monday), for occupancy math. */
export function countWeekdayInRange(
  from: string,
  to: string,
  weekday: number,
): number {
  const lo = new Date(`${from}T00:00:00`);
  const hi = new Date(`${to}T00:00:00`);
  if (hi < lo) return 0;
  // JS getDay(): 0=Sunday — convert to 0=Monday
  const loWd = (lo.getDay() + 6) % 7;
  const offset = (weekday - loWd + 7) % 7;
  const first = new Date(lo);
  first.setDate(lo.getDate() + offset);
  if (first > hi) return 0;
  return Math.floor((hi.getTime() - first.getTime()) / 86_400_000 / 7) + 1;
}
