"use client";

import { useEffect, useState } from "react";
import {
  Calendar,
  Search,
  Filter,
  RefreshCw,
  Trophy,
  Globe2,
  Clock,
  Sparkles,
  ExternalLink,
  ChevronRight,
  X,
  Layers,
  GraduationCap,
  Flame,
  Users,
  MapPin,
  Laptop,
  CheckCircle2,
  AlertTriangle,
} from "lucide-react";
import { fetchApi } from "@/lib/api-client";
import { useLatest } from "@/lib/use-latest";
import { formatDate } from "@/lib/utils";

interface EventCategoryItem {
  id: string;
  slug: string;
  name: string;
}

interface EventItem {
  id: string;
  name: string;
  organizer: string | null;
  event_type: string;
  delivery_mode: string;
  location_text: string | null;
  city: string | null;
  country: string | null;
  registration_url: string;
  event_website: string | null;
  registration_opens_at: string | null;
  registration_deadline: string | null;
  start_date: string | null;
  end_date: string | null;
  prize_summary: string | null;
  has_cash_prizes: boolean;
  prize_amount_usd_est: number | null;
  is_free_participation: boolean;
  student_eligible: boolean | null;
  international_eligible: boolean | null;
  status: string;
  source_platform: string;
  source_url: string;
  discovered_at: string;
  categories: EventCategoryItem[];
}

interface EventDetail extends EventItem {
  description: string;
  eligibility_text: string | null;
  participation_requirements: string | null;
}

interface EventStats {
  total_active_events: number;
  open_registration_count: number;
  closing_soon_count: number;
  total_cash_prize_usd: number;
  student_eligible_count: number;
}

const CATEGORY_TABS = [
  { key: "", label: "All Opportunities" },
  { key: "ai", label: "AI & GenAI" },
  { key: "machine-learning", label: "Machine Learning" },
  { key: "web-dev", label: "Web & Full-Stack" },
  { key: "blockchain", label: "Web3 & Blockchain" },
  { key: "data-science", label: "Data Science" },
  { key: "cybersecurity", label: "Cybersecurity & CTF" },
  { key: "cloud", label: "Cloud & DevOps" },
  { key: "entrepreneurship", label: "Grants & Startups" },
];

export default function EventsPage() {
  const [events, setEvents] = useState<EventItem[]>([]);
  const [stats, setStats] = useState<EventStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedEvent, setSelectedEvent] = useState<EventDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Filters
  const [category, setCategory] = useState("");
  const [deliveryMode, setDeliveryMode] = useState("");
  const [hasCashOnly, setHasCashOnly] = useState(false);
  const [studentOnly, setStudentOnly] = useState(false);
  const [search, setSearch] = useState("");

  const loadData = async () => {
    setLoading(true);
    const queryParts = [];
    if (category) queryParts.push(`category=${encodeURIComponent(category)}`);
    if (deliveryMode) queryParts.push(`delivery_mode=${encodeURIComponent(deliveryMode)}`);
    if (hasCashOnly) queryParts.push("has_cash_prizes=true");
    if (studentOnly) queryParts.push("student_eligible=true");
    if (search) queryParts.push(`search=${encodeURIComponent(search)}`);

    const queryStr = queryParts.length ? `?${queryParts.join("&")}` : "";

    const [eventsRes, statsRes] = await Promise.all([
      fetchApi<EventItem[]>(`/events${queryStr}`),
      fetchApi<EventStats>("/events/stats"),
    ]);

    if (eventsRes.data) {
      setEvents(eventsRes.data);
    }
    if (statsRes.data) {
      setStats(statsRes.data);
    }
    setLoading(false);
  };

  // Dropdown filters re-fetch immediately; text search re-fetches on Enter/submit.
  const loadDataRef = useLatest(loadData);
  useEffect(() => {
    loadDataRef.current();
  }, [category, deliveryMode, hasCashOnly, studentOnly, loadDataRef]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    loadData();
  };

  const handleViewDetail = async (id: string) => {
    setDetailLoading(true);
    const res = await fetchApi<EventDetail>(`/events/${id}`);
    if (res.data) {
      setSelectedEvent(res.data);
    }
    setDetailLoading(false);
  };

  const formatDeadlineText = (deadlineStr: string | null, status: string) => {
    if (!deadlineStr) return { text: "No deadline specified", color: "text-muted-foreground" };
    const deadline = new Date(deadlineStr);
    const now = new Date();
    const diffHours = (deadline.getTime() - now.getTime()) / (1000 * 60 * 60);

    if (diffHours < 0) {
      return { text: "Registration Closed", color: "text-muted-foreground" };
    }
    if (diffHours <= 24) {
      return { text: `Closes in ${Math.ceil(diffHours)} hours!`, color: "text-red-400 font-semibold" };
    }
    const days = Math.ceil(diffHours / 24);
    if (days <= 7) {
      return { text: `Closing in ${days} days`, color: "text-amber-400 font-semibold" };
    }
    return { text: `Deadline: ${formatDate(deadlineStr)}`, color: "text-emerald-400" };
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "REGISTRATION_CLOSING_SOON":
        return (
          <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-0.5 text-[10px] font-semibold text-amber-400">
            <span className="h-1.5 w-1.5 animate-ping rounded-full bg-amber-400" />
            Closing Soon
          </span>
        );
      case "OPEN_REGISTRATION":
        return (
          <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-0.5 text-[10px] font-semibold text-emerald-400">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
            Open Registration
          </span>
        );
      case "ONGOING":
        return (
          <span className="inline-flex items-center gap-1 rounded-full border border-blue-500/30 bg-blue-500/10 px-2.5 py-0.5 text-[10px] font-semibold text-blue-400">
            Ongoing Hackathon
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 rounded-full border border-muted bg-muted/40 px-2.5 py-0.5 text-[10px] font-medium text-muted-foreground">
            {status.replace(/_/g, " ")}
          </span>
        );
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">EventRadar</h1>
          <p className="text-sm text-muted-foreground">
            Developer hackathons, AI challenges, and technology grant discovery engine.
          </p>
        </div>
        <button
          onClick={loadData}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium text-foreground hover:bg-muted"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh Pipeline
        </button>
      </div>

      {/* KPI Stats Bar */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <div className="rounded-xl border border-border bg-card/60 p-4 shadow-sm backdrop-blur-md">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted-foreground">Active Opportunities</span>
            <Calendar className="h-4 w-4 text-purple-400" />
          </div>
          <div className="mt-2 text-2xl font-bold">
            {stats ? stats.total_active_events : "..."}
          </div>
          <div className="mt-1 text-[11px] text-muted-foreground">
            {stats ? `${stats.open_registration_count} open for registration` : "Scanning feeds"}
          </div>
        </div>

        <div className="rounded-xl border border-border bg-card/60 p-4 shadow-sm backdrop-blur-md">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted-foreground">Closing Soon (&lt;7 Days)</span>
            <Clock className="h-4 w-4 text-amber-400" />
          </div>
          <div className="mt-2 text-2xl font-bold text-amber-400">
            {stats ? stats.closing_soon_count : "..."}
          </div>
          <div className="mt-1 text-[11px] text-muted-foreground">Urgent submissions pending</div>
        </div>

        <div className="rounded-xl border border-border bg-card/60 p-4 shadow-sm backdrop-blur-md">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted-foreground">Cash Prize Pool</span>
            <Trophy className="h-4 w-4 text-emerald-400" />
          </div>
          <div className="mt-2 text-2xl font-bold text-emerald-400">
            {stats ? `$${stats.total_cash_prize_usd.toLocaleString("en-US", { maximumFractionDigits: 0 })}` : "..."}
          </div>
          <div className="mt-1 text-[11px] text-muted-foreground">Verified public prize purses</div>
        </div>

        <div className="rounded-xl border border-border bg-card/60 p-4 shadow-sm backdrop-blur-md">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted-foreground">Student &amp; Free Eligible</span>
            <GraduationCap className="h-4 w-4 text-blue-400" />
          </div>
          <div className="mt-2 text-2xl font-bold text-blue-400">
            {stats ? stats.student_eligible_count : "..."}
          </div>
          <div className="mt-1 text-[11px] text-muted-foreground">Zero entry fee required</div>
        </div>
      </div>

      {/* Category Pills */}
      <div className="flex gap-2 overflow-x-auto pb-2 scrollbar-none">
        {CATEGORY_TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setCategory(tab.key)}
            className={`whitespace-nowrap rounded-lg px-3 py-1.5 text-xs font-medium transition ${
              category === tab.key
                ? "bg-purple-600 text-white shadow-md shadow-purple-600/20"
                : "border border-border bg-card/50 text-muted-foreground hover:bg-muted"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between rounded-xl border border-border bg-card/50 p-3">
        <form onSubmit={handleSearchSubmit} className="relative flex-1">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search hackathons, themes (LLMs, DeFi, Python), or organizers..."
            className="w-full rounded-lg border border-input bg-muted/40 pl-9 pr-3 py-1.5 text-xs text-foreground placeholder-muted-foreground focus:border-primary focus:outline-none"
          />
        </form>

        <div className="flex flex-wrap items-center gap-2">
          {/* Delivery Mode */}
          <select
            value={deliveryMode}
            onChange={(e) => setDeliveryMode(e.target.value)}
            className="rounded-lg border border-input bg-card px-2.5 py-1.5 text-xs text-foreground focus:border-primary focus:outline-none"
          >
            <option value="">All Formats</option>
            <option value="VIRTUAL">Virtual / Online</option>
            <option value="PHYSICAL">Physical / On-site</option>
            <option value="HYBRID">Hybrid</option>
          </select>

          {/* Cash Prizes Only */}
          <button
            type="button"
            onClick={() => setHasCashOnly(!hasCashOnly)}
            className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition ${
              hasCashOnly
                ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-400"
                : "border-border bg-card text-muted-foreground hover:bg-muted"
            }`}
          >
            <Trophy className="h-3.5 w-3.5" />
            Cash Prizes Only
          </button>

          {/* Student Eligible Only */}
          <button
            type="button"
            onClick={() => setStudentOnly(!studentOnly)}
            className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition ${
              studentOnly
                ? "border-blue-500/50 bg-blue-500/10 text-blue-400"
                : "border-border bg-card text-muted-foreground hover:bg-muted"
            }`}
          >
            <GraduationCap className="h-3.5 w-3.5" />
            Student Friendly
          </button>
        </div>
      </div>

      {/* Events Grid */}
      {loading ? (
        <div className="flex h-64 items-center justify-center">
          <div className="flex flex-col items-center gap-3 text-muted-foreground">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
            <span className="text-xs">Querying EventRadar knowledgebase...</span>
          </div>
        </div>
      ) : events.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border py-16 text-center">
          <Calendar className="h-10 w-10 text-muted-foreground/40" />
          <h3 className="mt-3 text-sm font-semibold">No hackathons or events found</h3>
          <p className="mt-1 text-xs text-muted-foreground max-w-sm">
            Try adjusting your search criteria, clearing the cash filter, or triggering an EventRadar discovery run from the Sources console.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {events.map((ev) => {
            const dl = formatDeadlineText(ev.registration_deadline, ev.status);
            return (
              <div
                key={ev.id}
                onClick={() => handleViewDetail(ev.id)}
                className="group relative flex flex-col justify-between overflow-hidden rounded-xl border border-border bg-card/60 p-5 shadow-sm transition hover:border-purple-500/40 hover:bg-card/90 hover:shadow-md cursor-pointer"
              >
                <div>
                  {/* Top Bar */}
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] font-medium text-muted-foreground truncate">
                      {ev.organizer || "Independent Organizer"}
                    </span>
                    {getStatusBadge(ev.status)}
                  </div>

                  {/* Title */}
                  <h3 className="mt-2.5 text-base font-semibold tracking-tight text-foreground group-hover:text-purple-400 line-clamp-2">
                    {ev.name}
                  </h3>

                  {/* Format & Location */}
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span className="inline-flex items-center gap-1 rounded bg-muted/60 px-2 py-0.5 text-[11px]">
                      {ev.delivery_mode === "VIRTUAL" ? (
                        <>
                          <Laptop className="h-3 w-3 text-blue-400" /> Online
                        </>
                      ) : (
                        <>
                          <MapPin className="h-3 w-3 text-amber-400" /> {ev.location_text || "Physical"}
                        </>
                      )}
                    </span>

                    {ev.student_eligible && (
                      <span className="inline-flex items-center gap-1 rounded bg-blue-500/10 px-2 py-0.5 text-[11px] text-blue-400">
                        <GraduationCap className="h-3 w-3" /> Students
                      </span>
                    )}

                    <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
                      <Layers className="h-3 w-3" /> {ev.source_platform}
                    </span>
                  </div>

                  {/* Prize Badge */}
                  {ev.prize_summary && (
                    <div className="mt-3 flex items-center gap-1.5 rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-1.5 text-xs font-semibold text-emerald-400">
                      <Trophy className="h-4 w-4 shrink-0 text-emerald-400" />
                      <span className="truncate">{ev.prize_summary}</span>
                    </div>
                  )}

                  {/* Category Tags */}
                  <div className="mt-3 flex flex-wrap gap-1">
                    {ev.categories.slice(0, 3).map((cat) => (
                      <span
                        key={cat.id}
                        className="rounded bg-muted/50 px-2 py-0.5 text-[10px] text-muted-foreground"
                      >
                        {cat.name}
                      </span>
                    ))}
                    {ev.categories.length > 3 && (
                      <span className="rounded bg-muted/50 px-1.5 py-0.5 text-[10px] text-muted-foreground">
                        +{ev.categories.length - 3}
                      </span>
                    )}
                  </div>
                </div>

                {/* Footer */}
                <div className="mt-5 flex items-center justify-between border-t border-border/60 pt-3 text-xs">
                  <span className={`text-[11px] ${dl.color}`}>{dl.text}</span>
                  <div className="flex items-center gap-1 text-[11px] font-medium text-purple-400 group-hover:translate-x-0.5 transition">
                    Details <ChevronRight className="h-3.5 w-3.5" />
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Slide-over Detail Drawer */}
      {selectedEvent && (
        <div className="fixed inset-0 z-50 flex justify-end bg-background/80 backdrop-blur-sm">
          <div className="relative flex h-full w-full max-w-xl flex-col bg-card shadow-2xl border-l border-border animate-in slide-in-from-right duration-200">
            {/* Drawer Header */}
            <div className="flex items-start justify-between border-b border-border p-6">
              <div className="space-y-1 pr-6">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold uppercase tracking-wider text-purple-400">
                    {selectedEvent.event_type}
                  </span>
                  {getStatusBadge(selectedEvent.status)}
                </div>
                <h2 className="text-xl font-bold tracking-tight text-foreground">
                  {selectedEvent.name}
                </h2>
                <p className="text-xs text-muted-foreground">
                  Organized by: <span className="text-foreground">{selectedEvent.organizer || "Independent Host"}</span>
                </p>
              </div>
              <button
                onClick={() => setSelectedEvent(null)}
                className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {/* Drawer Body */}
            <div className="flex-1 overflow-y-auto p-6 space-y-6">
              {/* Prize Summary Banner */}
              {selectedEvent.prize_summary && (
                <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4">
                  <div className="flex items-center gap-2 text-sm font-semibold text-emerald-400">
                    <Trophy className="h-5 w-5" />
                    <span>Prize Pool &amp; Awards</span>
                  </div>
                  <p className="mt-1 text-xs text-emerald-300/90">
                    {selectedEvent.prize_summary}
                  </p>
                </div>
              )}

              {/* Timeline Card */}
              <div className="rounded-xl border border-border bg-muted/20 p-4 space-y-3">
                <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Event Timeline &amp; Deadlines
                </h4>
                <div className="grid grid-cols-2 gap-3 text-xs">
                  <div>
                    <span className="text-muted-foreground">Registration Deadline:</span>
                    <p className="mt-0.5 font-medium text-foreground">
                      {selectedEvent.registration_deadline
                        ? formatDate(selectedEvent.registration_deadline)
                        : "Open until capacity / start"}
                    </p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Event Period:</span>
                    <p className="mt-0.5 font-medium text-foreground">
                      {selectedEvent.start_date
                        ? `${formatDate(selectedEvent.start_date)} - ${selectedEvent.end_date ? formatDate(selectedEvent.end_date) : "TBD"}`
                        : "Self-paced / Ongoing"}
                    </p>
                  </div>
                </div>
              </div>

              {/* Format & Eligibility */}
              <div className="rounded-xl border border-border bg-muted/20 p-4 space-y-3">
                <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Format &amp; Eligibility
                </h4>
                <div className="grid grid-cols-2 gap-3 text-xs">
                  <div>
                    <span className="text-muted-foreground">Delivery Format:</span>
                    <p className="mt-0.5 font-medium text-foreground">{selectedEvent.delivery_mode}</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Participation Fee:</span>
                    <p className="mt-0.5 font-medium text-foreground">
                      {selectedEvent.is_free_participation ? "100% Free" : "Entry Fee Required"}
                    </p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Student Participation:</span>
                    <p className="mt-0.5 font-medium text-foreground">
                      {selectedEvent.student_eligible ? "Students Welcome & Encouraged" : "Unspecified"}
                    </p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Location:</span>
                    <p className="mt-0.5 font-medium text-foreground">
                      {selectedEvent.location_text || "Virtual (Global)"}
                    </p>
                  </div>
                </div>
              </div>

              {/* Category Tags */}
              <div>
                <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                  Themes &amp; Technologies
                </h4>
                <div className="flex flex-wrap gap-1.5">
                  {selectedEvent.categories.map((c) => (
                    <span
                      key={c.id}
                      className="rounded-lg border border-border bg-muted/50 px-2.5 py-1 text-xs text-foreground"
                    >
                      {c.name}
                    </span>
                  ))}
                </div>
              </div>

              {/* Description */}
              <div>
                <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                  Event Overview &amp; Description
                </h4>
                <div className="prose prose-sm dark:prose-invert max-w-none text-xs leading-relaxed text-muted-foreground whitespace-pre-line">
                  {selectedEvent.description}
                </div>
              </div>

              {/* Source Provenance */}
              <div className="rounded-xl border border-border/60 bg-muted/10 p-3 text-xs text-muted-foreground">
                <span className="font-semibold text-foreground">Discovery Provenance:</span> Sighted via{" "}
                <span className="text-purple-400 font-medium">{selectedEvent.source_platform}</span> on{" "}
                {formatDate(selectedEvent.discovered_at)}.
              </div>
            </div>

            {/* Drawer Footer Actions */}
            <div className="border-t border-border p-6 bg-card/60 flex items-center gap-3">
              <a
                href={selectedEvent.registration_url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex-1 inline-flex items-center justify-center gap-2 rounded-lg bg-purple-600 py-2.5 text-xs font-semibold text-white shadow-md shadow-purple-600/20 hover:bg-purple-500 transition"
              >
                Register on Official Portal <ExternalLink className="h-3.5 w-3.5" />
              </a>
              {selectedEvent.event_website && selectedEvent.event_website !== selectedEvent.registration_url && (
                <a
                  href={selectedEvent.event_website}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="rounded-lg border border-border bg-card px-3 py-2.5 text-xs font-medium text-foreground hover:bg-muted transition"
                >
                  Event Website
                </a>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
