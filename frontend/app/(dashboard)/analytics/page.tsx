"use client";

import { BarChart3, TrendingUp, Globe2, Layers } from "lucide-react";

export default function AnalyticsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Analytics & Intelligence Metrics</h1>
        <p className="text-sm text-muted-foreground">Discoveries over time, geographic breakdowns, and technology trends.</p>
      </div>

      <div className="rounded-xl border border-dashed border-border bg-card/40 p-12 text-center backdrop-blur-md">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-blue-500/10 text-blue-400">
          <BarChart3 className="h-6 w-6" />
        </div>
        <h3 className="mt-4 text-base font-semibold">Interactive Recharts Analytics (Phase 7)</h3>
        <p className="mx-auto mt-2 max-w-md text-xs text-muted-foreground">
          Aggregated discovery charts (Nigeria/EMEA regional breakdown, jobs by tech stack, hackathon prize pools) will be activated in Phase 7.
        </p>
      </div>
    </div>
  );
}
