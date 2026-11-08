"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Building2,
  Briefcase,
  Calendar,
  Database,
  Radar,
  ShieldCheck,
  CheckCircle2,
  Clock,
  ArrowUpRight,
} from "lucide-react";
import { fetchApi } from "@/lib/api-client";

export default function OverviewPage() {
  const [sourcesCount, setSourcesCount] = useState<number>(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadData() {
      const res = await fetchApi("/sources");
      if (res.data) {
        setSourcesCount(res.data.length);
      }
      setLoading(false);
    }
    loadData();
  }, []);

  const stats = [
    {
      title: "BusinessRadar",
      metric: "Ready to Crawl",
      desc: "POI & Commercial SME discovery",
      icon: Building2,
      href: "/businesses",
      color: "text-blue-400",
      bgColor: "bg-blue-500/10",
      borderColor: "border-blue-500/20",
    },
    {
      title: "JobRadar",
      metric: "Ready to Crawl",
      desc: "ATS & Remote tech boards",
      icon: Briefcase,
      href: "/jobs",
      color: "text-emerald-400",
      bgColor: "bg-emerald-500/10",
      borderColor: "border-emerald-500/20",
    },
    {
      title: "EventRadar",
      metric: "Ready to Crawl",
      desc: "Hackathons, grants & ML cups",
      icon: Calendar,
      href: "/events",
      color: "text-purple-400",
      bgColor: "bg-purple-500/10",
      borderColor: "border-purple-500/20",
    },
    {
      title: "Configured Sources",
      metric: loading ? "..." : `${sourcesCount} Sources`,
      desc: "Nigeria & Global Adapters Seeded",
      icon: Database,
      href: "/sources",
      color: "text-amber-400",
      bgColor: "bg-amber-500/10",
      borderColor: "border-amber-500/20",
    },
  ];

  return (
    <div className="space-y-8">
      {/* Page Title */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Intelligence Command Center</h1>
        <p className="text-sm text-muted-foreground">
          Autonomous public web discovery, verification, and enrichment platform.
        </p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
        {stats.map((stat) => (
          <div
            key={stat.title}
            className={`relative overflow-hidden rounded-xl border ${stat.borderColor} bg-card/60 p-5 shadow-sm backdrop-blur-md`}
          >
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-muted-foreground">{stat.title}</span>
              <div className={`flex h-8 w-8 items-center justify-center rounded-lg ${stat.bgColor} ${stat.color}`}>
                <stat.icon className="h-4 w-4" />
              </div>
            </div>
            <div className="mt-3">
              <div className="text-xl font-bold tracking-tight">{stat.metric}</div>
              <p className="mt-1 text-xs text-muted-foreground">{stat.desc}</p>
            </div>
            <div className="mt-4 border-t border-border/40 pt-3">
              <Link
                href={stat.href}
                className="flex items-center gap-1 text-xs font-medium text-primary hover:underline"
              >
                Access Module <ArrowUpRight className="h-3.5 w-3.5" />
              </Link>
            </div>
          </div>
        ))}
      </div>

      {/* Infrastructure & Security Health */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Core Architecture Status */}
        <div className="rounded-xl border border-border bg-card/60 p-6 shadow-sm backdrop-blur-md lg:col-span-2">
          <div className="flex items-center justify-between border-b border-border pb-4">
            <div>
              <h2 className="text-base font-semibold">Shared Scraping & Pipeline Subsystem</h2>
              <p className="text-xs text-muted-foreground">Component verification and policy enforcement</p>
            </div>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-1 text-xs font-medium text-emerald-400">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
              Subsystems Ready
            </span>
          </div>

          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="flex items-start gap-3 rounded-lg border border-border/60 bg-muted/20 p-3.5">
              <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0 mt-0.5" />
              <div>
                <span className="text-xs font-semibold">SSRF Network Guard</span>
                <p className="text-[11px] text-muted-foreground mt-0.5">
                  Pre-connect DNS resolver pins and blocks 127.0.0.0/8, 169.254.169.254, and RFC 1918.
                </p>
              </div>
            </div>

            <div className="flex items-start gap-3 rounded-lg border border-border/60 bg-muted/20 p-3.5">
              <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0 mt-0.5" />
              <div>
                <span className="text-xs font-semibold">Politeness & Robots.txt</span>
                <p className="text-[11px] text-muted-foreground mt-0.5">
                  Per-domain token bucket rate limiting and 24h robots.txt policy caching.
                </p>
              </div>
            </div>

            <div className="flex items-start gap-3 rounded-lg border border-border/60 bg-muted/20 p-3.5">
              <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0 mt-0.5" />
              <div>
                <span className="text-xs font-semibold">11-Stage Pipeline Isolation</span>
                <p className="text-[11px] text-muted-foreground mt-0.5">
                  Discover → Fetch → Extract → Normalize → Validate → Deduplicate → Enrich → Store.
                </p>
              </div>
            </div>

            <div className="flex items-start gap-3 rounded-lg border border-border/60 bg-muted/20 p-3.5">
              <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0 mt-0.5" />
              <div>
                <span className="text-xs font-semibold">Optional AI Intelligence</span>
                <p className="text-[11px] text-muted-foreground mt-0.5">
                  Decoupled LLM abstraction (Gemini, OpenAI, Local vLLM) with cost & token logs.
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Quick Launch Panel */}
        <div className="rounded-xl border border-border bg-card/60 p-6 shadow-sm backdrop-blur-md">
          <h2 className="text-base font-semibold">Discovery Quick Actions</h2>
          <p className="text-xs text-muted-foreground">Trigger crawl runs from registered adapters</p>

          <div className="mt-5 space-y-3">
            <Link
              href="/sources"
              className="flex items-center justify-between rounded-lg border border-border bg-muted/40 p-3 text-xs font-medium text-foreground transition-colors hover:bg-muted"
            >
              <span>Manage Source Registry</span>
              <ArrowUpRight className="h-4 w-4 text-muted-foreground" />
            </Link>

            <Link
              href="/tasks"
              className="flex items-center justify-between rounded-lg border border-border bg-muted/40 p-3 text-xs font-medium text-foreground transition-colors hover:bg-muted"
            >
              <span>Inspect Background Tasks & DLQ</span>
              <ArrowUpRight className="h-4 w-4 text-muted-foreground" />
            </Link>

            <div className="rounded-lg border border-dashed border-border p-3.5 text-center">
              <span className="text-[11px] text-muted-foreground">
                Phase 1 complete. Proceeding to Phase 2 (Scraping Engine & Workers).
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
