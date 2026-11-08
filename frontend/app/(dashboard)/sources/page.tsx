"use client";

import { useEffect, useState } from "react";
import {
  Database,
  CheckCircle2,
  AlertTriangle,
  Play,
  RefreshCw,
  Power,
  Shield,
  Layers,
} from "lucide-react";
import { fetchApi } from "@/lib/api-client";
import { formatDate } from "@/lib/utils";

interface SourceItem {
  id: string;
  slug: string;
  name: string;
  module_type: "BUSINESS" | "JOB" | "EVENT";
  source_category: string;
  base_url: string;
  collection_method: string;
  adapter_key: string;
  requires_credentials: boolean;
  required_env_vars: string[];
  config_status: "READY" | "AWAITING_CONFIGURATION" | "DISABLED" | "ERROR";
  rate_limit_rpm: number;
  crawl_budget_pages: number;
  is_enabled: boolean;
  last_success_at: string | null;
  total_records_collected: number;
}

export default function SourcesPage() {
  const [sources, setSources] = useState<SourceItem[]>([]);
  const [filterModule, setFilterModule] = useState<string>("ALL");
  const [loading, setLoading] = useState(true);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  const loadSources = async () => {
    setLoading(true);
    const res = await fetchApi<SourceItem[]>("/sources");
    if (res.data) {
      setSources(res.data);
    }
    setLoading(false);
  };

  useEffect(() => {
    loadSources();
  }, []);

  const handleToggle = async (id: string) => {
    const res = await fetchApi(`/sources/${id}/toggle`, { method: "POST" });
    if (res.data) {
      loadSources();
    }
  };

  const handleCheckConfig = async (id: string) => {
    const res = await fetchApi(`/sources/${id}/check-config`, { method: "POST" });
    if (res.data) {
      setActionMessage(`${res.data.slug}: ${res.data.message}`);
      loadSources();
      setTimeout(() => setActionMessage(null), 5000);
    }
  };

  const handleTriggerRun = async (sourceId: string, sourceName: string) => {
    const res = await fetchApi("/tasks/trigger", {
      method: "POST",
      body: JSON.stringify({
        source_id: sourceId,
        trigger_type: "MANUAL",
        search_params: {},
      }),
    });

    if (res.error) {
      setActionMessage(`Error triggering ${sourceName}: ${res.error}`);
    } else {
      setActionMessage(`Successfully queued discovery run for: ${sourceName}`);
    }
    setTimeout(() => setActionMessage(null), 5000);
  };

  const filtered = sources.filter((s) => {
    if (filterModule === "ALL") return true;
    return s.module_type === filterModule;
  });

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Shared Source Registry</h1>
          <p className="text-sm text-muted-foreground">
            Centralized discovery source catalogue with independent rate limits, credentials check, and adapter status.
          </p>
        </div>
        <button
          onClick={loadSources}
          className="flex items-center gap-2 rounded-lg border border-border bg-card px-3.5 py-2 text-xs font-medium text-foreground hover:bg-muted"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh Registry
        </button>
      </div>

      {actionMessage && (
        <div className="flex items-center gap-2 rounded-lg border border-primary/40 bg-primary/10 p-3 text-xs text-primary">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          <span>{actionMessage}</span>
        </div>
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

      {/* Sources Table */}
      <div className="overflow-hidden rounded-xl border border-border bg-card/60 shadow-sm backdrop-blur-md">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-border bg-muted/30 text-muted-foreground">
              <tr>
                <th className="px-5 py-3 font-semibold">Source Name & Slug</th>
                <th className="px-4 py-3 font-semibold">Module</th>
                <th className="px-4 py-3 font-semibold">Method</th>
                <th className="px-4 py-3 font-semibold">Status & Credentials</th>
                <th className="px-4 py-3 font-semibold">Limits</th>
                <th className="px-4 py-3 font-semibold">Last Sighting</th>
                <th className="px-5 py-3 text-right font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {loading ? (
                <tr>
                  <td colSpan={7} className="px-5 py-8 text-center text-muted-foreground">
                    Loading sources...
                  </td>
                </tr>
              ) : filtered.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-5 py-8 text-center text-muted-foreground">
                    No sources found for this filter.
                  </td>
                </tr>
              ) : (
                filtered.map((s) => {
                  const isReady = s.config_status === "READY";
                  return (
                    <tr key={s.id} className="transition-colors hover:bg-muted/20">
                      <td className="px-5 py-3.5">
                        <div className="font-semibold text-foreground">{s.name}</div>
                        <div className="font-mono text-[11px] text-muted-foreground">{s.slug}</div>
                      </td>
                      <td className="px-4 py-3.5">
                        <span
                          className={`inline-flex rounded px-2 py-0.5 text-[10px] font-semibold ${
                            s.module_type === "BUSINESS"
                              ? "bg-blue-500/10 text-blue-400"
                              : s.module_type === "JOB"
                              ? "bg-emerald-500/10 text-emerald-400"
                              : "bg-purple-500/10 text-purple-400"
                          }`}
                        >
                          {s.module_type}
                        </span>
                      </td>
                      <td className="px-4 py-3.5 text-muted-foreground">
                        <span className="font-mono text-[11px]">{s.collection_method}</span>
                      </td>
                      <td className="px-4 py-3.5">
                        {isReady ? (
                          <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-0.5 text-[11px] font-medium text-emerald-400">
                            <CheckCircle2 className="h-3 w-3" />
                            Ready
                          </span>
                        ) : (
                          <div className="space-y-1">
                            <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/20 bg-amber-500/10 px-2.5 py-0.5 text-[11px] font-medium text-amber-400">
                              <AlertTriangle className="h-3 w-3" />
                              Awaiting Config
                            </span>
                            {s.required_env_vars.length > 0 && (
                              <div className="font-mono text-[10px] text-muted-foreground">
                                Requires: {s.required_env_vars.join(", ")}
                              </div>
                            )}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3.5 text-muted-foreground">
                        <div>{s.rate_limit_rpm} req/min</div>
                        <div className="text-[10px]">Budget: {s.crawl_budget_pages} pgs</div>
                      </td>
                      <td className="px-4 py-3.5 text-muted-foreground">
                        {formatDate(s.last_success_at)}
                      </td>
                      <td className="px-5 py-3.5 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => handleCheckConfig(s.id)}
                            title="Verify required environment variables"
                            className="rounded border border-border bg-muted/40 p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                          >
                            <Shield className="h-3.5 w-3.5" />
                          </button>
                          <button
                            onClick={() => handleToggle(s.id)}
                            title={s.is_enabled ? "Disable Source" : "Enable Source"}
                            className={`rounded border border-border p-1.5 ${
                              s.is_enabled
                                ? "bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20"
                                : "bg-muted text-muted-foreground hover:text-foreground"
                            }`}
                          >
                            <Power className="h-3.5 w-3.5" />
                          </button>
                          <button
                            onClick={() => handleTriggerRun(s.id, s.name)}
                            disabled={!s.is_enabled}
                            title="Trigger Discovery Run"
                            className="flex items-center gap-1 rounded bg-primary px-2.5 py-1.5 text-[11px] font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
                          >
                            <Play className="h-3 w-3 fill-current" />
                            Run
                          </button>
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
