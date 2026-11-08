"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Radar,
  Building2,
  Briefcase,
  Calendar,
  Activity,
  Database,
  BrainCircuit,
  BarChart3,
  Settings,
  Bookmark,
} from "lucide-react";
import { cn } from "@/lib/utils";

const navigation = [
  { name: "Overview", href: "/overview", icon: Activity },
  { name: "BusinessRadar", href: "/businesses", icon: Building2 },
  { name: "JobRadar", href: "/jobs", icon: Briefcase },
  { name: "EventRadar", href: "/events", icon: Calendar },
  { name: "Saved Records", href: "/saved", icon: Bookmark },
  { name: "Discovery Tasks", href: "/tasks", icon: Radar },
  { name: "Data Sources", href: "/sources", icon: Database },
  { name: "AI Intelligence", href: "/intelligence", icon: BrainCircuit },
  { name: "Analytics", href: "/analytics", icon: BarChart3 },
  { name: "Settings", href: "/settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r border-border bg-card/60 backdrop-blur-md">
      {/* Brand Header */}
      <div className="flex h-16 items-center gap-3 border-b border-border px-6">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-md shadow-primary/20">
          <Radar className="h-5 w-5" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <span className="font-bold text-base tracking-tight">RADAR</span>
            <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold text-primary">v1.0</span>
          </div>
          <p className="text-[11px] text-muted-foreground">Unified Web Intelligence</p>
        </div>
      </div>

      {/* Navigation List */}
      <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-4">
        {navigation.map((item) => {
          const isActive = pathname === item.href || (item.href !== "/overview" && pathname?.startsWith(item.href));
          return (
            <Link
              key={item.name}
              href={item.href}
              className={cn(
                "group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-all duration-150",
                isActive
                  ? "bg-primary/10 text-primary font-semibold shadow-sm"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
            >
              <item.icon className={cn("h-4 w-4 shrink-0 transition-transform group-hover:scale-105", isActive ? "text-primary" : "text-muted-foreground")} />
              <span>{item.name}</span>
            </Link>
          );
        })}
      </nav>

      {/* Footer System Status */}
      <div className="border-t border-border p-4">
        <div className="rounded-lg border border-border bg-muted/40 p-3">
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground">Scraper Engines</span>
            <span className="flex items-center gap-1.5 text-emerald-400 font-medium">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
              Online
            </span>
          </div>
          <div className="mt-2 text-[11px] text-muted-foreground">
            Politeness: Robots.txt & SSRF Guard Active
          </div>
        </div>
      </div>
    </aside>
  );
}
