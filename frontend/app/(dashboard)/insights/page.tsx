"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  Briefcase,
  Building2,
  CalendarDays,
  Clock,
  ExternalLink,
  Lightbulb,
  Loader2,
  Phone,
} from "lucide-react";
import { fetchApi } from "@/lib/api-client";
import { formatDate } from "@/lib/utils";
import { BarList, Panel, type NamedCount } from "@/components/bar-list";

interface Insights {
  generated_at: string;
  highlights: string[];
  jobs: {
    total_active: number;
    new_last_7_days: number;
    remote_share_pct: number;
    with_salary_pct: number;
    top_skills: NamedCount[];
    top_companies: NamedCount[];
    by_remote_status: Record<string, number>;
    by_experience: Record<string, number>;
    by_category: Record<string, number>;
  };
  events: {
    total_active: number;
    closing_within_7_days: number;
    total_prize_usd: number;
    next_deadlines: {
      id: string;
      name: string;
      organizer: string | null;
      deadline: string;
      prize_summary: string | null;
      url: string;
    }[];
    by_type: Record<string, number>;
    by_delivery_mode: Record<string, number>;
  };
  businesses: {
    total: number;
    avg_lead_score: number;
    no_website_count: number;
    top_leads: {
      id: string;
      name: string;
      category: string | null;
      city: string | null;
      lead_score: number;
      has_phone: boolean;
      website_status: string;
    }[];
    by_city: Record<string, number>;
    top_categories: NamedCount[];
  };
  freshness: { jobs: string | null; events: string | null; businesses: string | null };
}

const LABELS: Record<string, string> = {
  AI_ML: "AI / ML",
  DEVOPS: "DevOps",
  OTHER_TECH: "Other tech",
  LEAD_MANAGER: "Lead / manager",
  STAFF_PRINCIPAL: "Staff / principal",
  NO_WEBSITE_FOUND: "No website",
  HAS_WEBSITE: "Has website",
  NOT_CHECKED: "Website not checked",
};

const label = (s: string) => {
  if (LABELS[s]) return LABELS[s];
  const t = s.replace(/_/g, " ").toLowerCase();
  return t.charAt(0).toUpperCase() + t.slice(1);
};

const toCounts = (m: Record<string, number>): NamedCount[] =>
  Object.entries(m)
    .map(([name, count]) => ({ name: label(name), count }))
    .sort((a, b) => b.count - a.count);

function daysUntil(iso: string): string {
  const hours = (new Date(iso).getTime() - Date.now()) / 3_600_000;
  if (hours < 1) return "within the hour";
  if (hours < 24) return `in ${Math.floor(hours)} hour${Math.floor(hours) === 1 ? "" : "s"}`;
  const days = Math.round(hours / 24);
  return days === 1 ? "in 1 day" : `in ${days} days`;
}

function Stat({ icon: Icon, label, value, hint }: { icon: typeof Briefcase; label: string; value: string; hint: string }) {
  return (
    <div className="rounded-xl border border-border bg-card/60 p-5 backdrop-blur-md">
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>{label}</span>
        <Icon className="h-4 w-4 text-primary" />
      </div>
      <div className="mt-2 text-2xl font-bold tabular-nums">{value}</div>
      <p className="mt-1 text-[11px] text-muted-foreground">{hint}</p>
    </div>
  );
}

export default function InsightsPage() {
  const [data, setData] = useState<Insights | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchApi<Insights>("/insights").then((r) => {
      if (r.data) setData(r.data);
      else setError(r.error ?? "Could not load insights.");
    });
  }, []);

  if (error) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-destructive/40 bg-destructive/10 p-4 text-sm">
        <AlertTriangle className="h-4 w-4 text-destructive" /> {error}
      </div>
    );
  }
  if (!data) {
    return (
      <div className="flex items-center gap-2 p-8 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Crunching the numbers…
      </div>
    );
  }

  const { jobs, events, businesses, freshness } = data;
  const empty = !jobs.total_active && !events.total_active && !businesses.total;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Insights</h1>
        <p className="text-sm text-muted-foreground">
          Trends across the jobs, events and businesses RADAR has collected. Calculated directly from the data with
          fixed rules, with no AI involved.
        </p>
      </div>

      {empty ? (
        <div className="rounded-xl border border-dashed border-border bg-card/40 p-12 text-center">
          <Lightbulb className="mx-auto h-6 w-6 text-muted-foreground" />
          <h3 className="mt-3 text-base font-semibold">No data yet</h3>
          <p className="mx-auto mt-1 max-w-md text-xs text-muted-foreground">
            Run a source from{" "}
            <Link href="/sources" className="text-primary underline-offset-2 hover:underline">
              Data Sources
            </Link>{" "}
            and insights will appear here once records are collected.
          </p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
            <Stat icon={Briefcase} label="Active jobs" value={jobs.total_active.toLocaleString()}
                  hint={`${jobs.new_last_7_days.toLocaleString()} new in the last 7 days`} />
            <Stat icon={Briefcase} label="Remote share" value={`${jobs.remote_share_pct}%`}
                  hint={`${jobs.with_salary_pct}% publish a salary`} />
            <Stat icon={CalendarDays} label="Open events" value={events.total_active.toLocaleString()}
                  hint={`${events.closing_within_7_days} closing within 7 days`} />
            <Stat icon={Building2} label="Businesses" value={businesses.total.toLocaleString()}
                  hint={`Average lead score ${businesses.avg_lead_score}`} />
          </div>

          {data.highlights.length > 0 && (
            <Panel title="Highlights" subtitle="Plain-language observations generated from the numbers below">
              <ul className="grid gap-2 md:grid-cols-2">
                {data.highlights.map((h) => (
                  <li key={h} className="flex gap-2 rounded-lg border border-border/60 bg-muted/20 p-3 text-xs">
                    <Lightbulb className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" />
                    <span>{h}</span>
                  </li>
                ))}
              </ul>
            </Panel>
          )}

          <div className="grid gap-5 lg:grid-cols-3">
            <Panel title="Most requested skills" subtitle="Active jobs listing each skill">
              <BarList items={jobs.top_skills} total={jobs.total_active} unit="jobs" />
            </Panel>
            <Panel title="Top hiring companies" subtitle="Open roles per company">
              <BarList items={jobs.top_companies} total={jobs.total_active} unit="roles" />
            </Panel>
            <Panel title="Seniority" subtitle="Experience level of active jobs">
              <BarList items={toCounts(jobs.by_experience)} total={jobs.total_active} unit="jobs" />
            </Panel>
            <Panel title="Work arrangement" subtitle="Remote, hybrid or onsite">
              <BarList items={toCounts(jobs.by_remote_status)} total={jobs.total_active} unit="jobs" />
            </Panel>
            <Panel title="Job categories">
              <BarList items={toCounts(jobs.by_category)} total={jobs.total_active} unit="jobs" />
            </Panel>
            <Panel title="Event types" subtitle={events.total_prize_usd >= 1
              ? `About $${Math.round(events.total_prize_usd).toLocaleString()} in estimated prizes`
              : undefined}>
              <BarList items={toCounts(events.by_type)} total={events.total_active} unit="events" />
            </Panel>
          </div>

          <div className="grid gap-5 lg:grid-cols-2">
            <Panel title="Next event deadlines" subtitle="Soonest registration deadlines among open events">
              {events.next_deadlines.length ? (
                <ul className="divide-y divide-border/60">
                  {events.next_deadlines.map((e) => (
                    <li key={e.id} className="flex items-start justify-between gap-3 py-2.5 text-xs">
                      <div className="min-w-0">
                        <a href={e.url} target="_blank" rel="noopener noreferrer"
                           className="inline-flex items-center gap-1 font-medium hover:text-primary">
                          <span className="truncate">{e.name}</span>
                          <ExternalLink className="h-3 w-3 shrink-0" />
                        </a>
                        <p className="truncate text-muted-foreground">
                          {[e.organizer, e.prize_summary].filter(Boolean).join(" · ") || "No prize listed"}
                        </p>
                      </div>
                      <div className="shrink-0 text-right">
                        <div className="font-medium">{daysUntil(e.deadline)}</div>
                        <div className="text-muted-foreground">{formatDate(e.deadline)}</div>
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-muted-foreground">No upcoming deadlines.</p>
              )}
            </Panel>

            <Panel title="Best business leads"
                   subtitle={`Highest lead scores · ${businesses.no_website_count} of ${businesses.total} have no website`}>
              {businesses.top_leads.length ? (
                <ul className="divide-y divide-border/60">
                  {businesses.top_leads.map((b) => (
                    <li key={b.id} className="flex items-center justify-between gap-3 py-2.5 text-xs">
                      <div className="min-w-0">
                        <div className="truncate font-medium">{b.name}</div>
                        <p className="truncate text-muted-foreground">
                          {[b.category, b.city, label(b.website_status)].filter(Boolean).join(" · ")}
                        </p>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        {b.has_phone && <Phone className="h-3.5 w-3.5 text-muted-foreground" aria-label="Has phone" />}
                        <span className="rounded-md bg-primary/10 px-2 py-0.5 font-semibold tabular-nums text-primary">
                          {b.lead_score}
                        </span>
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-muted-foreground">No businesses yet.</p>
              )}
              <Link href="/businesses" className="mt-3 inline-block text-xs text-primary hover:underline">
                Open BusinessRadar →
              </Link>
            </Panel>
          </div>
        </>
      )}

      <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Clock className="h-3 w-3" />
        Latest records found: jobs {formatDate(freshness.jobs)}, events {formatDate(freshness.events)}, businesses{" "}
        {formatDate(freshness.businesses)}.
      </p>
    </div>
  );
}
