"use client";

import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from "recharts";
import type { NameType, ValueType } from "recharts/types/component/DefaultTooltipContent";
import { AlertTriangle, CheckCircle2, CircleDashed, Info, Loader2, XCircle } from "lucide-react";
import { fetchApi } from "@/lib/api-client";
import { formatDate } from "@/lib/utils";
import { BarList, Panel, type NamedCount } from "@/components/bar-list";

interface DailyDiscoveries { date: string; jobs: number; events: number; businesses: number }
interface DailyRuns { date: string; completed: number; partial: number; failed: number }
interface SourceHealth {
  id: string;
  name: string;
  module_type: string;
  is_enabled: boolean;
  runs: number;
  completed: number;
  partial: number;
  failed: number;
  success_rate_pct: number | null;
  avg_duration_seconds: number | null;
  avg_records_created: number | null;
  last_run_at: string | null;
  last_run_status: string | null;
  last_error_at: string | null;
  last_error_message: string | null;
  open_failed_tasks: number;
  total_records_collected: number;
}
interface Analytics {
  days: number;
  discoveries: DailyDiscoveries[];
  discoveries_by_source: { source: string; entity_type: "JOB" | "EVENT" | "BUSINESS"; count: number }[];
  runs: DailyRuns[];
  source_health: SourceHealth[];
  geography: {
    jobs_by_country: NamedCount[];
    jobs_remote: number;
    jobs_total: number;
    nigeria_jobs: number;
    businesses_by_city: NamedCount[];
    events_by_mode: NamedCount[];
  };
  prizes_by_deadline_week: { week_start: string; prize_usd: number; events: number }[];
}

// Categorical slots validated against the dark card surface (dataviz palette, dark column).
const SERIES = { jobs: "#3987e5", events: "#d95926", businesses: "#199e70" };
// Reserved status colours: only for run outcomes, always paired with a label.
const STATUS = { completed: "#0ca30c", partial: "#fab219", failed: "#d03b3b" };
const AXIS = { fill: "hsl(215 20% 65%)", fontSize: 11 };
const GRID = "hsl(216 34% 17%)";
const SURFACE = "hsl(224 71% 7%)";
const RANGES = [7, 30, 90];
const ENTITY_LABEL = { JOB: "Jobs", EVENT: "Events", BUSINESS: "Businesses" };

const compact = (v: number) => (v >= 1000 ? `${+(v / 1000).toFixed(1)}k` : String(v));
const RUN_ORDER = ["completed", "partial", "failed"];

const shortDate = (iso: string) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });

function duration(s: number | null): string {
  if (s == null) return "—";
  if (s < 90) return `${Math.round(s)} s`;
  if (s < 5400) return `${Math.round(s / 60)} min`;
  return `${(s / 3600).toFixed(1)} h`;
}

function ChartTooltip({ active, payload, label, money }: TooltipContentProps<ValueType, NameType> & { money?: boolean }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-border bg-popover px-3 py-2 text-xs shadow-lg">
      <div className="mb-1 font-medium">{label}</div>
      {payload.map((p) => (
        <div key={String(p.dataKey)} className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-sm" style={{ background: p.color }} />
          <span className="text-muted-foreground">{p.name}</span>
          <span className="ml-auto pl-3 tabular-nums">
            {money ? `$${Math.round(Number(p.value)).toLocaleString()}` : Number(p.value).toLocaleString()}
          </span>
        </div>
      ))}
      {money && payload[0]?.payload?.events != null && (
        <div className="mt-1 text-muted-foreground">{payload[0].payload.events} events close this week</div>
      )}
    </div>
  );
}

/** One small chart per record type: each has its own scale, so 30 events stay visible next to 2,000 jobs. */
function DailyBars({ data, field, name }: { data: DailyDiscoveries[]; field: keyof typeof SERIES; name: string }) {
  const rows = data.map((d) => ({ label: shortDate(d.date), value: d[field] }));
  const total = rows.reduce((n, r) => n + r.value, 0);
  return (
    <div>
      <div className="flex items-baseline justify-between text-xs">
        <span className="flex items-center gap-1.5 font-medium">
          <span className="h-2 w-2 rounded-sm" style={{ background: SERIES[field] }} />
          {name}
        </span>
        <span className="tabular-nums text-muted-foreground">{total.toLocaleString()} found</span>
      </div>
      <div className="mt-2 h-28">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 4, right: 0, bottom: 0, left: -8 }}>
            <CartesianGrid vertical={false} stroke={GRID} strokeDasharray="2 4" />
            <XAxis dataKey="label" tick={AXIS} tickLine={false} axisLine={false} interval="preserveStartEnd" minTickGap={24} />
            <YAxis tick={AXIS} tickLine={false} axisLine={false} allowDecimals={false} width={36} tickFormatter={compact} />
            <Tooltip cursor={{ fill: "hsl(216 34% 17% / 0.5)" }} content={(p) => <ChartTooltip {...p} />} />
            <Bar dataKey="value" name={name} fill={SERIES[field]} radius={[4, 4, 0, 0]} maxBarSize={18} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function RunStatusBadge({ status }: { status: string | null }) {
  if (!status) return <span className="text-muted-foreground">Never run</span>;
  const map: Record<string, { icon: typeof CheckCircle2; color: string; text: string }> = {
    COMPLETED: { icon: CheckCircle2, color: STATUS.completed, text: "Completed" },
    PARTIAL_FAILURE: { icon: AlertTriangle, color: STATUS.partial, text: "Partly failed" },
    FAILED: { icon: XCircle, color: STATUS.failed, text: "Failed" },
  };
  const m = map[status] ?? { icon: CircleDashed, color: "hsl(215 20% 65%)", text: status.charAt(0) + status.slice(1).toLowerCase() };
  const Icon = m.icon;
  return (
    <span className="inline-flex items-center gap-1">
      <Icon className="h-3.5 w-3.5" style={{ color: m.color }} />
      {m.text}
    </span>
  );
}

export default function AnalyticsPage() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<Analytics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchApi<Analytics>(`/analytics?days=${days}`).then((r) => {
      if (cancelled) return;
      if (r.data) {
        setData(r.data);
        setError(null);
      } else setError(r.error ?? "Could not load analytics.");
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [days]);

  const activeDays = data ? data.discoveries.filter((d) => d.jobs || d.events || d.businesses).length : 0;
  const runRows = data?.runs.map((r) => ({ ...r, label: shortDate(r.date) })) ?? [];
  const prizeRows = data?.prizes_by_deadline_week.map((w) => ({ ...w, label: `Wk of ${shortDate(w.week_start)}` })) ?? [];
  const geo = data?.geography;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Analytics</h1>
          <p className="text-sm text-muted-foreground">
            How collection changes over time and how each crawler is doing. For what&apos;s in the data right now, see Insights.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {loading && data && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
          <div className="flex rounded-lg border border-border bg-card/60 p-0.5 text-xs" role="group" aria-label="Time range">
            {RANGES.map((r) => (
              <button
                key={r}
                onClick={() => setDays(r)}
                aria-pressed={days === r}
                className={`rounded-md px-3 py-1.5 transition-colors ${
                  days === r ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {r} days
              </button>
            ))}
          </div>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-destructive/40 bg-destructive/10 p-4 text-sm">
          <AlertTriangle className="h-4 w-4 text-destructive" /> {error}
        </div>
      )}

      {!data && !error && (
        <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading analytics…
        </div>
      )}

      {data && geo && (
        <>
          {activeDays < 7 && (
            <div className="flex items-start gap-2 rounded-xl border border-border bg-muted/20 p-3 text-xs text-muted-foreground">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
              <span>
                Records were found on only {activeDays} of the last {data.days} days, so the trend charts are mostly
                empty for now. They fill in as scheduled runs build up history.
              </span>
            </div>
          )}

          <Panel title="Discoveries over time" subtitle="New records found per day (UTC). Each chart has its own scale.">
            <div className="grid gap-6 md:grid-cols-3">
              <DailyBars data={data.discoveries} field="jobs" name="Jobs" />
              <DailyBars data={data.discoveries} field="events" name="Events" />
              <DailyBars data={data.discoveries} field="businesses" name="Businesses" />
            </div>
          </Panel>

          <div className="grid gap-5 lg:grid-cols-3">
            <Panel title="Crawler runs per day" subtitle="Finished runs by outcome" className="lg:col-span-2">
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={runRows} margin={{ top: 4, right: 0, bottom: 0, left: -8 }}>
                    <CartesianGrid vertical={false} stroke={GRID} strokeDasharray="2 4" />
                    <XAxis dataKey="label" tick={AXIS} tickLine={false} axisLine={false} interval="preserveStartEnd" minTickGap={24} />
                    <YAxis tick={AXIS} tickLine={false} axisLine={false} allowDecimals={false} width={36} tickFormatter={compact} />
                    <Tooltip cursor={{ fill: "hsl(216 34% 17% / 0.5)" }} content={(p) => <ChartTooltip {...p} />} />
                    <Legend
                      iconType="square"
                      iconSize={8}
                      wrapperStyle={{ fontSize: 11, color: AXIS.fill }}
                      itemSorter={(item) => RUN_ORDER.indexOf(String(item.dataKey))}
                    />
                    <Bar dataKey="completed" name="Completed" stackId="r" fill={STATUS.completed} stroke={SURFACE} strokeWidth={1} maxBarSize={18} />
                    <Bar dataKey="partial" name="Partly failed" stackId="r" fill={STATUS.partial} stroke={SURFACE} strokeWidth={1} maxBarSize={18} />
                    <Bar dataKey="failed" name="Failed" stackId="r" fill={STATUS.failed} stroke={SURFACE} strokeWidth={1} radius={[4, 4, 0, 0]} maxBarSize={18} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Panel>
            <Panel title="Found per source" subtitle={`Records discovered in the last ${data.days} days`}>
              <BarList
                items={data.discoveries_by_source.map((s) => ({ name: `${s.source} · ${ENTITY_LABEL[s.entity_type]}`, count: s.count }))}
                unit="records"
              />
            </Panel>
          </div>

          <Panel title="Source health" subtitle={`Runs in the last ${data.days} days. Partly failed runs count as half a success.`}>
            <div className="-mx-5 overflow-x-auto">
              <table className="w-full min-w-[860px] text-left text-xs">
                <thead className="text-[11px] text-muted-foreground">
                  <tr className="border-b border-border">
                    <th className="px-5 py-2 font-medium">Source</th>
                    <th className="px-3 py-2 text-right font-medium">Runs</th>
                    <th className="px-3 py-2 text-right font-medium">Success</th>
                    <th className="px-3 py-2 text-right font-medium">Avg time</th>
                    <th className="px-3 py-2 text-right font-medium">Avg new</th>
                    <th className="px-3 py-2 font-medium">Last run</th>
                    <th className="px-3 py-2 text-right font-medium">Failed tasks</th>
                    <th className="px-5 py-2 font-medium">Last error</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/60">
                  {data.source_health.map((s) => (
                    <tr key={s.id} className={s.is_enabled ? "" : "opacity-60"}>
                      <td className="px-5 py-2.5">
                        <div className="font-medium">{s.name}</div>
                        <div className="text-[11px] text-muted-foreground">
                          {ENTITY_LABEL[s.module_type as keyof typeof ENTITY_LABEL] ?? s.module_type}
                          {s.is_enabled ? "" : " · disabled"} · {s.total_records_collected.toLocaleString()} records processed
                        </div>
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums" title={`${s.completed} completed, ${s.partial} partly failed, ${s.failed} failed`}>
                        {s.runs}
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums">
                        {s.success_rate_pct == null ? "—" : `${s.success_rate_pct}%`}
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums">{duration(s.avg_duration_seconds)}</td>
                      <td className="px-3 py-2.5 text-right tabular-nums">
                        {s.avg_records_created == null ? "—" : Math.round(s.avg_records_created).toLocaleString()}
                      </td>
                      <td className="px-3 py-2.5">
                        <RunStatusBadge status={s.last_run_status} />
                        {s.last_run_at && <div className="text-[11px] text-muted-foreground">{formatDate(s.last_run_at)}</div>}
                      </td>
                      <td className="px-3 py-2.5 text-right tabular-nums">
                        {s.open_failed_tasks ? (
                          <span className="inline-flex items-center gap-1">
                            <AlertTriangle className="h-3.5 w-3.5" style={{ color: STATUS.partial }} />
                            {s.open_failed_tasks}
                          </span>
                        ) : (
                          "0"
                        )}
                      </td>
                      <td className="max-w-[260px] px-5 py-2.5 text-muted-foreground">
                        {s.last_error_message ? (
                          <span title={s.last_error_message} className="line-clamp-2">
                            {s.last_error_at && <span className="text-foreground">{formatDate(s.last_error_at)}: </span>}
                            {s.last_error_message}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <div className="grid gap-5 lg:grid-cols-3">
            <Panel
              title="Jobs by country"
              subtitle={`${geo.nigeria_jobs.toLocaleString()} in Nigeria · ${geo.jobs_remote.toLocaleString()} marked fully remote`}
            >
              <BarList items={geo.jobs_by_country} total={geo.jobs_total} unit="jobs" />
              <p className="mt-3 text-[11px] text-muted-foreground">
                &quot;Anywhere&quot; covers listings whose location is Worldwide, Remote or similar.
              </p>
            </Panel>
            <Panel title="Businesses by city">
              <BarList items={geo.businesses_by_city} unit="businesses" />
            </Panel>
            <Panel title="Open events by format">
              <BarList
                items={geo.events_by_mode.map((m) => ({ name: m.name.charAt(0) + m.name.slice(1).toLowerCase(), count: m.count }))}
                unit="events"
              />
            </Panel>
          </div>

          <Panel title="Prize money by deadline week" subtitle="Estimated cash prizes of open events, by the week registration closes (next 12 weeks)">
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={prizeRows} margin={{ top: 4, right: 0, bottom: 0, left: 4 }}>
                  <CartesianGrid vertical={false} stroke={GRID} strokeDasharray="2 4" />
                  <XAxis dataKey="label" tick={AXIS} tickLine={false} axisLine={false} interval="preserveStartEnd" minTickGap={16} />
                  <YAxis
                    tick={AXIS}
                    tickLine={false}
                    axisLine={false}
                    width={56}
                    tickFormatter={(v: number) => (v >= 1_000_000 ? `$${v / 1_000_000}M` : v >= 1000 ? `$${v / 1000}k` : `$${v}`)}
                  />
                  <Tooltip cursor={{ fill: "hsl(216 34% 17% / 0.5)" }} content={(p) => <ChartTooltip {...p} money />} />
                  <Bar dataKey="prize_usd" name="Prize money" fill={SERIES.jobs} radius={[4, 4, 0, 0]} maxBarSize={36} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Panel>
        </>
      )}
    </div>
  );
}
