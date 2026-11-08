"use client";

import { useEffect, useState } from "react";
import {
  Radar,
  RefreshCw,
  Clock,
  CheckCircle2,
  AlertCircle,
  XCircle,
  StopCircle,
  AlertTriangle,
  RotateCcw,
} from "lucide-react";
import { fetchApi } from "@/lib/api-client";
import { formatDate } from "@/lib/utils";

interface SourceRunItem {
  id: string;
  source_id: string;
  trigger_type: string;
  status: "QUEUED" | "RUNNING" | "COMPLETED" | "PARTIAL_FAILURE" | "FAILED" | "CANCELLED";
  search_params: Record<string, any>;
  pages_fetched: number;
  records_extracted: number;
  records_created: number;
  records_updated: number;
  errors_count: number;
  started_at: string | null;
  finished_at: string | null;
  error_summary: string | null;
  created_at: string;
}

interface DeadLetterItem {
  id: string;
  scraping_task_id: string;
  source_id: string | null;
  stage: string;
  input_snapshot: Record<string, any>;
  error_type: string;
  error_message: string;
  resolved_at: string | null;
  created_at: string;
}

export default function TasksPage() {
  const [activeTab, setActiveTab] = useState<"runs" | "dlq">("runs");
  const [runs, setRuns] = useState<SourceRunItem[]>([]);
  const [dlqItems, setDlqItems] = useState<DeadLetterItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  const loadData = async () => {
    setLoading(true);
    const [runsRes, dlqRes] = await Promise.all([
      fetchApi<SourceRunItem[]>("/tasks/runs"),
      fetchApi<DeadLetterItem[]>("/tasks/dead-letter"),
    ]);

    if (runsRes.data) setRuns(runsRes.data);
    if (dlqRes.data) setDlqItems(dlqRes.data);
    setLoading(false);
  };

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 10000); // 10s auto-refresh
    return () => clearInterval(interval);
  }, []);

  const handleCancel = async (runId: string) => {
    const res = await fetchApi(`/tasks/runs/${runId}/cancel`, { method: "POST" });
    if (res.error) {
      setActionMessage(`Error cancelling: ${res.error}`);
    } else {
      setActionMessage(`Run ${runId.slice(0, 8)} cancelled.`);
      loadData();
    }
    setTimeout(() => setActionMessage(null), 5000);
  };

  const handleRetryDlq = async (dlqId: string) => {
    const res = await fetchApi(`/tasks/dead-letter/${dlqId}/retry`, { method: "POST" });
    if (res.error) {
      setActionMessage(`Error retrying DLQ item: ${res.error}`);
    } else {
      setActionMessage(`DLQ item re-queued for execution.`);
      loadData();
    }
    setTimeout(() => setActionMessage(null), 5000);
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "COMPLETED":
        return (
          <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-400">
            <CheckCircle2 className="h-3 w-3" /> Completed
          </span>
        );
      case "RUNNING":
        return (
          <span className="inline-flex items-center gap-1 rounded-full border border-blue-500/20 bg-blue-500/10 px-2 py-0.5 text-[11px] font-medium text-blue-400 animate-pulse">
            <Clock className="h-3 w-3" /> Running
          </span>
        );
      case "QUEUED":
        return (
          <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/20 bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-400">
            <Clock className="h-3 w-3" /> Queued
          </span>
        );
      case "PARTIAL_FAILURE":
        return (
          <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-300">
            <AlertTriangle className="h-3 w-3" /> Partial Success
          </span>
        );
      case "FAILED":
        return (
          <span className="inline-flex items-center gap-1 rounded-full border border-destructive/30 bg-destructive/10 px-2 py-0.5 text-[11px] font-medium text-red-400">
            <AlertCircle className="h-3 w-3" /> Failed
          </span>
        );
      case "CANCELLED":
        return (
          <span className="inline-flex items-center gap-1 rounded-full border border-border bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
            <XCircle className="h-3 w-3" /> Cancelled
          </span>
        );
      default:
        return <span className="text-muted-foreground">{status}</span>;
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Discovery Tasks & Background Runs</h1>
          <p className="text-sm text-muted-foreground">
            Monitor asynchronous pipeline stages, inspection metrics, and dead-letter queues.
          </p>
        </div>
        <button
          onClick={loadData}
          className="flex items-center gap-2 rounded-lg border border-border bg-card px-3.5 py-2 text-xs font-medium text-foreground hover:bg-muted"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </button>
      </div>

      {actionMessage && (
        <div className="flex items-center gap-2 rounded-lg border border-primary/40 bg-primary/10 p-3 text-xs text-primary">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          <span>{actionMessage}</span>
        </div>
      )}

      {/* View Tabs */}
      <div className="flex items-center gap-3 border-b border-border pb-3">
        <button
          onClick={() => setActiveTab("runs")}
          className={`flex items-center gap-2 rounded-lg px-3.5 py-1.5 text-xs font-semibold transition-colors ${
            activeTab === "runs"
              ? "bg-primary text-primary-foreground shadow-sm"
              : "text-muted-foreground hover:bg-muted hover:text-foreground"
          }`}
        >
          <span>Discovery Runs</span>
          <span className="rounded-full bg-black/30 px-1.5 py-0.2 text-[10px]">{runs.length}</span>
        </button>
        <button
          onClick={() => setActiveTab("dlq")}
          className={`flex items-center gap-2 rounded-lg px-3.5 py-1.5 text-xs font-semibold transition-colors ${
            activeTab === "dlq"
              ? "bg-amber-500 text-black shadow-sm"
              : "text-muted-foreground hover:bg-muted hover:text-foreground"
          }`}
        >
          <AlertTriangle className="h-3.5 w-3.5" />
          <span>Dead-Letter Queue (DLQ)</span>
          <span className="rounded-full bg-black/20 px-1.5 py-0.2 text-[10px] font-bold">{dlqItems.length}</span>
        </button>
      </div>

      {activeTab === "runs" ? (
        /* Runs Table */
        <div className="overflow-hidden rounded-xl border border-border bg-card/60 shadow-sm backdrop-blur-md">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-border bg-muted/30 text-muted-foreground">
                <tr>
                  <th className="px-5 py-3 font-semibold">Run ID</th>
                  <th className="px-4 py-3 font-semibold">Trigger</th>
                  <th className="px-4 py-3 font-semibold">Status</th>
                  <th className="px-4 py-3 font-semibold">Pages Fetched</th>
                  <th className="px-4 py-3 font-semibold">Records Extracted</th>
                  <th className="px-4 py-3 font-semibold">Created / Updated</th>
                  <th className="px-4 py-3 font-semibold">Started At</th>
                  <th className="px-5 py-3 text-right font-semibold">Control</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {loading && runs.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-5 py-8 text-center text-muted-foreground">
                      Loading runs...
                    </td>
                  </tr>
                ) : runs.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-5 py-8 text-center text-muted-foreground">
                      No discovery runs executed yet. Go to Data Sources to trigger a run.
                    </td>
                  </tr>
                ) : (
                  runs.map((r) => (
                    <tr key={r.id} className="transition-colors hover:bg-muted/20">
                      <td className="px-5 py-3.5 font-mono text-[11px] text-foreground">
                        {r.id.slice(0, 8)}...
                      </td>
                      <td className="px-4 py-3.5">
                        <span className="rounded bg-muted px-2 py-0.5 text-[10px] font-semibold text-muted-foreground">
                          {r.trigger_type}
                        </span>
                      </td>
                      <td className="px-4 py-3.5">{getStatusBadge(r.status)}</td>
                      <td className="px-4 py-3.5 font-mono">{r.pages_fetched}</td>
                      <td className="px-4 py-3.5 font-mono text-emerald-400 font-semibold">
                        {r.records_extracted}
                      </td>
                      <td className="px-4 py-3.5 text-muted-foreground">
                        {r.records_created} new / {r.records_updated} upd
                      </td>
                      <td className="px-4 py-3.5 text-muted-foreground">{formatDate(r.started_at)}</td>
                      <td className="px-5 py-3.5 text-right">
                        {["QUEUED", "RUNNING"].includes(r.status) && (
                          <button
                            onClick={() => handleCancel(r.id)}
                            title="Cancel Task"
                            className="flex items-center gap-1 rounded bg-destructive/20 px-2 py-1 text-[11px] font-semibold text-red-400 hover:bg-destructive/30"
                          >
                            <StopCircle className="h-3 w-3" />
                            Cancel
                          </button>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        /* Dead-Letter Queue Table */
        <div className="overflow-hidden rounded-xl border border-amber-500/20 bg-card/60 shadow-sm backdrop-blur-md">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-border bg-muted/40 text-muted-foreground">
                <tr>
                  <th className="px-5 py-3 font-semibold">Failed Stage</th>
                  <th className="px-4 py-3 font-semibold">Error Type</th>
                  <th className="px-4 py-3 font-semibold">Error Message</th>
                  <th className="px-4 py-3 font-semibold">Input Snapshot</th>
                  <th className="px-4 py-3 font-semibold">Logged At</th>
                  <th className="px-5 py-3 text-right font-semibold">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {dlqItems.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-5 py-8 text-center text-muted-foreground">
                      No failed tasks in dead-letter queue. All pipeline executions healthy!
                    </td>
                  </tr>
                ) : (
                  dlqItems.map((item) => (
                    <tr key={item.id} className="hover:bg-muted/20">
                      <td className="px-5 py-3.5">
                        <span className="rounded bg-destructive/20 px-2 py-0.5 text-[10px] font-bold text-red-400">
                          {item.stage}
                        </span>
                      </td>
                      <td className="px-4 py-3.5 font-mono text-amber-400">{item.error_type}</td>
                      <td className="px-4 py-3.5 text-muted-foreground max-w-xs truncate" title={item.error_message}>
                        {item.error_message}
                      </td>
                      <td className="px-4 py-3.5 font-mono text-[10px] text-muted-foreground">
                        {JSON.stringify(item.input_snapshot)}
                      </td>
                      <td className="px-4 py-3.5 text-muted-foreground">{formatDate(item.created_at)}</td>
                      <td className="px-5 py-3.5 text-right">
                        <button
                          onClick={() => handleRetryDlq(item.id)}
                          className="flex items-center gap-1 rounded bg-amber-500/20 px-2.5 py-1 text-[11px] font-semibold text-amber-300 hover:bg-amber-500/30"
                        >
                          <RotateCcw className="h-3 w-3" />
                          Retry
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
