"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  CircleDashed,
  Clock,
  Loader2,
  Play,
  Power,
  RefreshCw,
  Shield,
  Square,
  XCircle,
} from "lucide-react";
import { fetchApi } from "@/lib/api-client";
import { getStoredUser } from "@/lib/auth";
import { formatDate } from "@/lib/utils";
import { describeSchedule, PRESET_CRONS, schedulePresets, timeAgo, timeUntil } from "@/lib/schedule";

interface RunSummary {
  id: string;
  status: "QUEUED" | "RUNNING" | "PAUSED" | "COMPLETED" | "PARTIAL_FAILURE" | "FAILED" | "CANCELLED";
  trigger_type: string;
  started_at: string | null;
  finished_at: string | null;
  pages_fetched: number;
  records_extracted: number;
  records_created: number;
  records_updated: number;
  errors_count: number;
  error_summary: string | null;
  created_at: string;
}

interface SourceItem {
  id: string;
  slug: string;
  name: string;
  module_type: "BUSINESS" | "JOB" | "EVENT";
  collection_method: string;
  required_env_vars: string[];
  config_status: "READY" | "AWAITING_CONFIGURATION" | "DISABLED" | "ERROR";
  rate_limit_rpm: number;
  crawl_budget_pages: number;
  adapter_config: { manual_only?: boolean; default_query?: string } & Record<string, unknown>;
  schedule_cron: string | null;
  is_enabled: boolean;
  last_success_at: string | null;
  total_records_collected: number;
  active_run: RunSummary | null;
  last_run: RunSummary | null;
  next_run_at: string | null;
}

type Message = { kind: "ok" | "error"; text: string };

const ACTIVE_POLL_MS = 4000; // while a run is going
const IDLE_POLL_MS = 60000; // otherwise, to notice scheduled runs starting

function ActivityCell({ s }: { s: SourceItem }) {
  const run = s.active_run;
  if (run) {
    const started = run.started_at ?? run.created_at;
    return (
      <div className="space-y-0.5">
        <div className="flex items-center gap-1.5 font-medium text-primary">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          {run.status === "QUEUED" ? "Queued, waiting for a worker" : run.status === "PAUSED" ? "Paused" : "Running"}
          {run.trigger_type === "SCHEDULED" && <span className="text-[10px] font-normal text-muted-foreground">(scheduled)</span>}
        </div>
        {run.status !== "QUEUED" && (
          <div className="text-[11px] text-muted-foreground">
            {run.pages_fetched} page{run.pages_fetched === 1 ? "" : "s"} · {run.records_created} new · {run.records_updated} updated
            {run.errors_count > 0 && <span className="text-amber-400"> · {run.errors_count} errors</span>}
          </div>
        )}
        <div className="text-[11px] text-muted-foreground">started {timeAgo(started)}</div>
      </div>
    );
  }
  const last = s.last_run;
  if (!last) return <span className="text-muted-foreground">Never run</span>;
  const when = last.finished_at ?? last.started_at ?? last.created_at;
  const look = {
    COMPLETED: { icon: CheckCircle2, color: "text-emerald-400", text: "Completed" },
    PARTIAL_FAILURE: { icon: AlertTriangle, color: "text-amber-400", text: "Partly failed" },
    FAILED: { icon: XCircle, color: "text-red-400", text: "Failed" },
    CANCELLED: { icon: Ban, color: "text-muted-foreground", text: "Stopped" },
  }[last.status as "COMPLETED" | "PARTIAL_FAILURE" | "FAILED" | "CANCELLED"] ?? {
    icon: CircleDashed, color: "text-muted-foreground", text: last.status,
  };
  const Icon = look.icon;
  return (
    <div className="space-y-0.5" title={last.error_summary ?? undefined}>
      <div className={`flex items-center gap-1.5 font-medium ${look.color}`}>
        <Icon className="h-3.5 w-3.5" />
        {look.text} <span className="font-normal text-muted-foreground" title={formatDate(when)}>{timeAgo(when)}</span>
      </div>
      <div className="text-[11px] text-muted-foreground">
        {last.records_created} new · {last.records_updated} updated
      </div>
      {last.error_summary && last.status !== "COMPLETED" && (
        <div className="max-w-[220px] truncate text-[11px] text-muted-foreground">{last.error_summary}</div>
      )}
    </div>
  );
}

export default function SourcesPage() {
  const [sources, setSources] = useState<SourceItem[]>([]);
  const [filterModule, setFilterModule] = useState<string>("ALL");
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<Message | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [roles, setRoles] = useState<string[]>([]);
  const [presets, setPresets] = useState<{ cron: string; label: string }[]>([]);
  const [searchFor, setSearchFor] = useState<SourceItem | null>(null); // manual-only search dialog
  const [query, setQuery] = useState("");
  const [, setTick] = useState(0); // re-render so "in 12 min" / "3 min ago" stay current

  const canRun = roles.some((r) => ["super_admin", "admin", "researcher"].includes(r));
  const canManage = roles.some((r) => ["super_admin", "admin"].includes(r));

  const loadSources = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    const res = await fetchApi<SourceItem[]>("/sources");
    if (res.data) setSources(res.data);
    if (!quiet) setLoading(false);
  }, []);

  useEffect(() => {
    setPresets(schedulePresets());
    setRoles((getStoredUser()?.roles ?? []).map((r) => r.name));
    fetchApi<{ roles: { name: string }[] }>("/auth/me").then((r) => {
      if (r.data) setRoles(r.data.roles.map((x) => x.name));
    });
    loadSources();
  }, [loadSources]);

  // Poll quickly while anything is running, slowly otherwise.
  const anyActive = useMemo(() => sources.some((s) => s.active_run), [sources]);
  useEffect(() => {
    const id = setInterval(() => {
      if (document.visibilityState === "visible") loadSources(true);
      setTick((t) => t + 1);
    }, anyActive ? ACTIVE_POLL_MS : IDLE_POLL_MS);
    return () => clearInterval(id);
  }, [anyActive, loadSources]);

  const flash = (m: Message) => {
    setMessage(m);
    setTimeout(() => setMessage((cur) => (cur === m ? null : cur)), 6000);
  };

  const handleToggle = async (id: string) => {
    const res = await fetchApi(`/sources/${id}/toggle`, { method: "POST" });
    if (res.data) loadSources(true);
    else flash({ kind: "error", text: res.error ?? "Could not change the source." });
  };

  const handleCheckConfig = async (id: string) => {
    const res = await fetchApi<{ slug: string; message: string }>(`/sources/${id}/check-config`, { method: "POST" });
    if (res.data) {
      flash({ kind: "ok", text: `${res.data.slug}: ${res.data.message}` });
      loadSources(true);
    }
  };

  const handleTriggerRun = async (s: SourceItem, searchParams: Record<string, string> = {}) => {
    setBusy(s.id);
    const res = await fetchApi("/tasks/trigger", {
      method: "POST",
      body: JSON.stringify({ source_id: s.id, trigger_type: "MANUAL", search_params: searchParams }),
    });
    setBusy(null);
    if (res.status === 403) {
      flash({ kind: "error", text: "Starting runs needs the researcher role or higher. An admin can change your role in Settings → Users." });
    } else if (res.error) {
      flash({ kind: "error", text: `${s.name}: ${res.error}` });
    } else {
      flash({ kind: "ok", text: `Started ${s.name}. Progress shows in the Activity column.` });
    }
    loadSources(true);
  };

  const handleStop = async (s: SourceItem) => {
    if (!s.active_run) return;
    setBusy(s.id);
    const res = await fetchApi(`/tasks/runs/${s.active_run.id}/cancel`, { method: "POST" });
    setBusy(null);
    if (res.error) flash({ kind: "error", text: `${s.name}: ${res.error}` });
    else flash({ kind: "ok", text: `Stopping ${s.name}. It finishes the page it's on first.` });
    loadSources(true);
  };

  const handleSchedule = async (s: SourceItem, cron: string) => {
    setBusy(s.id);
    const res = await fetchApi(`/sources/${s.id}`, { method: "PATCH", body: JSON.stringify({ schedule_cron: cron }) });
    setBusy(null);
    if (res.error) flash({ kind: "error", text: `${s.name}: ${res.error}` });
    else flash({ kind: "ok", text: `${s.name}: ${describeSchedule(cron)}.` });
    loadSources(true);
  };

  const filtered = sources.filter((s) => filterModule === "ALL" || s.module_type === filterModule);
  const scheduledCount = sources.filter((s) => s.next_run_at).length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Data Sources</h1>
          <p className="text-sm text-muted-foreground">
            Where RADAR collects data from, when each source runs next, and what it&apos;s doing right now.
            {scheduledCount > 0 && ` ${scheduledCount} of ${sources.length} run on a schedule.`}
          </p>
        </div>
        <button
          onClick={() => loadSources()}
          className="flex items-center gap-2 rounded-lg border border-border bg-card px-3.5 py-2 text-xs font-medium text-foreground hover:bg-muted"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${anyActive ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {message && (
        <div
          role={message.kind === "error" ? "alert" : "status"}
          className={`flex items-center gap-2 rounded-lg border p-3 text-xs ${
            message.kind === "error" ? "border-red-500/40 bg-red-500/10 text-red-300" : "border-primary/40 bg-primary/10 text-primary"
          }`}
        >
          {message.kind === "error" ? <AlertTriangle className="h-4 w-4 shrink-0" /> : <CheckCircle2 className="h-4 w-4 shrink-0" />}
          <span>{message.text}</span>
        </div>
      )}

      {!canRun && roles.length > 0 && (
        <p className="text-xs text-muted-foreground">
          You can view sources. Starting runs needs the researcher role, and changing schedules needs an admin.
        </p>
      )}

      {/* Module Filter Tabs */}
      <div className="flex items-center gap-2 border-b border-border pb-3">
        {["ALL", "BUSINESS", "JOB", "EVENT"].map((tab) => (
          <button
            key={tab}
            onClick={() => setFilterModule(tab)}
            className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
              filterModule === tab
                ? "bg-primary text-primary-foreground shadow-sm"
                : "text-muted-foreground hover:bg-muted hover:text-foreground"
            }`}
          >
            {tab === "ALL" ? "All Sources" : `${tab.charAt(0) + tab.slice(1).toLowerCase()}Radar`}
          </button>
        ))}
      </div>

      {searchFor && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="search-title">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const target = searchFor;
              setSearchFor(null);
              handleTriggerRun(target, query.trim() ? { query: query.trim() } : {});
            }}
            className="w-full max-w-md space-y-4 rounded-xl border border-border bg-card p-6 shadow-2xl"
          >
            <div>
              <h3 id="search-title" className="text-base font-bold">Search {searchFor.name}</h3>
              <p className="mt-1 text-xs text-muted-foreground">
                What and where to look for. Up to {searchFor.crawl_budget_pages * 20} results per run.
              </p>
            </div>
            <input
              autoFocus
              value={query}
              maxLength={200}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g. pharmacies in Lekki, Lagos"
              aria-label="Search for"
              className="w-full rounded-lg border border-input bg-muted/40 px-3 py-2 text-xs focus:border-primary focus:outline-none"
            />
            <p className="text-[11px] text-muted-foreground">
              Results are saved with a &quot;Google Maps&quot; label, kept out of CSV exports by default, and can all be
              removed from Settings → Integrations. Each run is a paid Google request.
            </p>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setSearchFor(null)} className="rounded-lg border border-border px-3 py-1.5 text-xs hover:bg-muted">
                Cancel
              </button>
              <button type="submit" className="inline-flex items-center gap-1 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground hover:bg-primary/90">
                <Play className="h-3 w-3 fill-current" /> Run search
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Sources Table */}
      <div className="overflow-hidden rounded-xl border border-border bg-card/60 shadow-sm backdrop-blur-md">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] text-left text-xs">
            <thead className="border-b border-border bg-muted/30 text-muted-foreground">
              <tr>
                <th className="px-5 py-3 font-semibold">Source</th>
                <th className="px-4 py-3 font-semibold">Status</th>
                <th className="px-4 py-3 font-semibold">Activity</th>
                <th className="px-4 py-3 font-semibold">Schedule</th>
                <th className="px-5 py-3 text-right font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {loading ? (
                <tr><td colSpan={5} className="px-5 py-8 text-center text-muted-foreground">Loading sources...</td></tr>
              ) : filtered.length === 0 ? (
                <tr><td colSpan={5} className="px-5 py-8 text-center text-muted-foreground">No sources found for this filter.</td></tr>
              ) : (
                filtered.map((s) => {
                  const isReady = s.config_status === "READY";
                  const cron = s.schedule_cron ?? "";
                  const options = PRESET_CRONS.includes(cron)
                    ? presets
                    : [...presets, { cron, label: describeSchedule(cron) }];
                  return (
                    <tr key={s.id} className={`align-top transition-colors hover:bg-muted/20 ${s.is_enabled ? "" : "opacity-60"}`}>
                      <td className="px-5 py-3.5">
                        <div className="font-semibold text-foreground">{s.name}</div>
                        <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                          <span
                            className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                              s.module_type === "BUSINESS"
                                ? "bg-blue-500/10 text-blue-400"
                                : s.module_type === "JOB"
                                ? "bg-emerald-500/10 text-emerald-400"
                                : "bg-purple-500/10 text-purple-400"
                            }`}
                          >
                            {s.module_type}
                          </span>
                          <span>{s.total_records_collected.toLocaleString()} records processed</span>
                          <span>· {s.rate_limit_rpm} req/min</span>
                        </div>
                      </td>
                      <td className="px-4 py-3.5">
                        {!s.is_enabled ? (
                          <span className="inline-flex items-center gap-1.5 text-muted-foreground"><Power className="h-3 w-3" /> Disabled</span>
                        ) : isReady ? (
                          <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-0.5 text-[11px] font-medium text-emerald-400">
                            <CheckCircle2 className="h-3 w-3" /> Ready
                          </span>
                        ) : (
                          <div className="space-y-1">
                            <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/20 bg-amber-500/10 px-2.5 py-0.5 text-[11px] font-medium text-amber-400">
                              <AlertTriangle className="h-3 w-3" /> Needs a key
                            </span>
                            {s.required_env_vars.length > 0 && (
                              <div className="font-mono text-[10px] text-muted-foreground">{s.required_env_vars.join(", ")}</div>
                            )}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3.5"><ActivityCell s={s} /></td>
                      <td className="px-4 py-3.5">
                        {s.adapter_config?.manual_only ? (
                          <span title="Google's terms don't allow bulk crawling, so this source only runs when you start it.">
                            Manual only
                          </span>
                        ) : canManage ? (
                          <select
                            value={cron}
                            disabled={busy === s.id}
                            onChange={(e) => handleSchedule(s, e.target.value)}
                            aria-label={`Schedule for ${s.name}`}
                            className="max-w-[200px] rounded-md border border-input bg-card px-2 py-1 text-xs disabled:opacity-60"
                          >
                            {options.map((o) => <option key={o.cron || "off"} value={o.cron}>{o.label}</option>)}
                          </select>
                        ) : (
                          <span>{describeSchedule(s.schedule_cron)}</span>
                        )}
                        <div className="mt-1 flex items-center gap-1 text-[11px] text-muted-foreground">
                          <Clock className="h-3 w-3" />
                          {s.next_run_at ? (
                            <span title={formatDate(s.next_run_at)}>Next run {timeUntil(s.next_run_at)}</span>
                          ) : !s.schedule_cron ? (
                            "Runs only when started"
                          ) : !s.is_enabled ? (
                            "Paused while disabled"
                          ) : (
                            "Waiting for its key"
                          )}
                        </div>
                      </td>
                      <td className="px-5 py-3.5 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => handleCheckConfig(s.id)}
                            title="Check required keys"
                            aria-label={`Check keys for ${s.name}`}
                            className="rounded border border-border bg-muted/40 p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                          >
                            <Shield className="h-3.5 w-3.5" />
                          </button>
                          <button
                            onClick={() => handleToggle(s.id)}
                            title={s.is_enabled ? "Disable source" : "Enable source"}
                            aria-label={s.is_enabled ? `Disable ${s.name}` : `Enable ${s.name}`}
                            className={`rounded border border-border p-1.5 ${
                              s.is_enabled
                                ? "bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20"
                                : "bg-muted text-muted-foreground hover:text-foreground"
                            }`}
                          >
                            <Power className="h-3.5 w-3.5" />
                          </button>
                          {s.active_run ? (
                            canManage ? (
                              <button
                                onClick={() => handleStop(s)}
                                disabled={busy === s.id}
                                className="flex w-[68px] items-center justify-center gap-1 rounded border border-red-500/40 bg-red-500/10 px-2.5 py-1.5 text-[11px] font-semibold text-red-300 hover:bg-red-500/20 disabled:opacity-50"
                              >
                                <Square className="h-3 w-3 fill-current" /> Stop
                              </button>
                            ) : (
                              <span className="flex w-[68px] items-center justify-center gap-1 rounded bg-primary/20 px-2.5 py-1.5 text-[11px] font-semibold text-primary">
                                <Loader2 className="h-3 w-3 animate-spin" /> Running
                              </span>
                            )
                          ) : (
                            <button
                              onClick={() => {
                                if (s.adapter_config?.manual_only) {
                                  setQuery(s.adapter_config.default_query ?? "");
                                  setSearchFor(s);
                                } else handleTriggerRun(s);
                              }}
                              disabled={!s.is_enabled || !isReady || busy === s.id}
                              title={!isReady ? "Add the required keys first" : "Start a run now"}
                              className="flex w-[68px] items-center justify-center gap-1 rounded bg-primary px-2.5 py-1.5 text-[11px] font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
                            >
                              {busy === s.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3 fill-current" />}
                              Run
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
