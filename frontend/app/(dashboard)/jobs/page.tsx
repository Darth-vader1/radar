"use client";

import { useEffect, useState } from "react";
import {
  Briefcase,
  Search,
  Filter,
  RefreshCw,
  MapPin,
  Globe2,
  ExternalLink,
  ChevronRight,
  X,
  Layers,
  LayoutGrid,
  List as ListIcon,
  Clock,
  Sparkles,
  Building,
} from "lucide-react";
import { fetchApi } from "@/lib/api-client";
import { SaveButton } from "@/components/save-button";
import { useLatest } from "@/lib/use-latest";
import { isRemotiveJob } from "@/lib/attribution";
import { formatDate } from "@/lib/utils";

interface JobSkillItem {
  id: string;
  skill_name: string;
}

interface JobItem {
  id: string;
  title: string;
  company_name: string;
  company_website: string | null;
  category: string;
  employment_type: string;
  remote_status: string;
  experience_level: string;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  location_text: string | null;
  city: string | null;
  country: string | null;
  application_url: string;
  source_platform: string;
  status: string;
  published_at: string | null;
  discovered_at: string;
  skills: JobSkillItem[];
  other_sources_count: number;
}

interface JobDetail extends JobItem {
  description: string;
  requirements_text: string | null;
  education_requirements: string | null;
  original_source_url: string;
}

const CATEGORIES = [
  { key: "", label: "All Roles" },
  { key: "SOFTWARE_ENGINEERING", label: "Software Engineering" },
  { key: "BACKEND", label: "Backend" },
  { key: "FRONTEND", label: "Frontend" },
  { key: "CLOUD", label: "Cloud & Infra" },
  { key: "DEVOPS", label: "DevOps / SRE" },
  { key: "AI_ML", label: "AI & Machine Learning" },
  { key: "DATA_SCIENCE", label: "Data Science" },
  { key: "CYBERSECURITY", label: "Cybersecurity" },
  { key: "PRODUCT_DESIGN", label: "Product Design" },
  { key: "PRODUCT_MANAGEMENT", label: "Product Management" },
];

export default function JobsPage() {
  const [jobs, setJobs] = useState<JobItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState<"cards" | "table">("cards");
  const [selectedJob, setSelectedJob] = useState<JobDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Filters
  const [category, setCategory] = useState("");
  const [remoteStatus, setRemoteStatus] = useState("");
  const [employmentType, setEmploymentType] = useState("");
  const [experienceLevel, setExperienceLevel] = useState("");
  const [search, setSearch] = useState("");

  const loadJobs = async () => {
    setLoading(true);
    const queryParts = [];
    if (category) queryParts.push(`category=${encodeURIComponent(category)}`);
    if (remoteStatus) queryParts.push(`remote_status=${encodeURIComponent(remoteStatus)}`);
    if (employmentType) queryParts.push(`employment_type=${encodeURIComponent(employmentType)}`);
    if (experienceLevel) queryParts.push(`experience_level=${encodeURIComponent(experienceLevel)}`);
    if (search) queryParts.push(`search=${encodeURIComponent(search)}`);

    const queryStr = queryParts.length ? `?${queryParts.join("&")}` : "";
    const res = await fetchApi<JobItem[]>(`/jobs${queryStr}`);
    if (res.data) {
      setJobs(res.data);
    }
    setLoading(false);
  };

  // Dropdown filters re-fetch immediately; text search re-fetches on Enter/submit.
  const loadJobsRef = useLatest(loadJobs);
  useEffect(() => {
    loadJobsRef.current();
  }, [category, remoteStatus, employmentType, experienceLevel, loadJobsRef]);

  const handleSelectJob = async (jobId: string) => {
    setDetailLoading(true);
    const res = await fetchApi<JobDetail>(`/jobs/${jobId}`);
    if (res.data) {
      setSelectedJob(res.data);
    }
    setDetailLoading(false);
  };

  const formatRemoteBadge = (status: string) => {
    switch (status) {
      case "REMOTE":
        return (
          <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-400">
            <Globe2 className="h-3 w-3" /> Remote
          </span>
        );
      case "HYBRID":
        return (
          <span className="inline-flex items-center gap-1 rounded-full border border-purple-500/30 bg-purple-500/10 px-2 py-0.5 text-[10px] font-semibold text-purple-400">
            Hybrid
          </span>
        );
      case "ONSITE":
        return (
          <span className="inline-flex items-center gap-1 rounded-full border border-blue-500/30 bg-blue-500/10 px-2 py-0.5 text-[10px] font-semibold text-blue-400">
            Onsite
          </span>
        );
      default:
        return null;
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">JobRadar</h1>
          <p className="text-sm text-muted-foreground">
            Developer vacancies, internships, and remote career openings unified with cross-platform deduplication.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* View Mode Toggle */}
          <div className="flex items-center rounded-lg border border-border bg-card p-0.5">
            <button
              onClick={() => setViewMode("cards")}
              className={`rounded p-1.5 transition-colors ${
                viewMode === "cards" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
              }`}
              title="Cards View"
            >
              <LayoutGrid className="h-4 w-4" />
            </button>
            <button
              onClick={() => setViewMode("table")}
              className={`rounded p-1.5 transition-colors ${
                viewMode === "table" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
              }`}
              title="Table View"
            >
              <ListIcon className="h-4 w-4" />
            </button>
          </div>

          <button
            onClick={loadJobs}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>
        </div>
      </div>

      {/* Category Pills Bar */}
      <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-none">
        {CATEGORIES.map((cat) => (
          <button
            key={cat.key}
            onClick={() => setCategory(cat.key)}
            className={`whitespace-nowrap rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
              category === cat.key
                ? "bg-primary text-primary-foreground shadow-sm"
                : "border border-border bg-card/60 text-muted-foreground hover:bg-muted hover:text-foreground"
            }`}
          >
            {cat.label}
          </button>
        ))}
      </div>

      {/* Filter Toolbar */}
      <div className="rounded-xl border border-border bg-card/60 p-4 shadow-sm backdrop-blur-md">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4 text-xs">
          {/* Remote Status */}
          <div>
            <label className="block text-[11px] font-medium text-muted-foreground mb-1">Workplace Type</label>
            <select
              value={remoteStatus}
              onChange={(e) => setRemoteStatus(e.target.value)}
              className="w-full rounded-lg border border-input bg-muted/40 px-2.5 py-1.5 text-foreground focus:border-primary focus:outline-none"
            >
              <option value="">All Workplace Types</option>
              <option value="REMOTE">Remote Only</option>
              <option value="HYBRID">Hybrid</option>
              <option value="ONSITE">Onsite</option>
            </select>
          </div>

          {/* Employment Type */}
          <div>
            <label className="block text-[11px] font-medium text-muted-foreground mb-1">Employment Type</label>
            <select
              value={employmentType}
              onChange={(e) => setEmploymentType(e.target.value)}
              className="w-full rounded-lg border border-input bg-muted/40 px-2.5 py-1.5 text-foreground focus:border-primary focus:outline-none"
            >
              <option value="">All Types</option>
              <option value="FULL_TIME">Full-time</option>
              <option value="INTERNSHIP">Internship</option>
              <option value="GRADUATE_TRAINEE">Graduate Trainee</option>
              <option value="CONTRACT">Contract</option>
            </select>
          </div>

          {/* Experience Level */}
          <div>
            <label className="block text-[11px] font-medium text-muted-foreground mb-1">Seniority</label>
            <select
              value={experienceLevel}
              onChange={(e) => setExperienceLevel(e.target.value)}
              className="w-full rounded-lg border border-input bg-muted/40 px-2.5 py-1.5 text-foreground focus:border-primary focus:outline-none"
            >
              <option value="">All Seniority Levels</option>
              <option value="INTERN">Intern / Student</option>
              <option value="ENTRY">Junior / Entry</option>
              <option value="MID">Mid-Level</option>
              <option value="SENIOR">Senior</option>
              <option value="STAFF_PRINCIPAL">Staff / Principal</option>
              <option value="LEAD_MANAGER">Lead / Manager</option>
            </select>
          </div>

          {/* Search */}
          <div>
            <label className="block text-[11px] font-medium text-muted-foreground mb-1">Search Vacancies</label>
            <div className="relative">
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && loadJobs()}
                placeholder="Title, skill, or company..."
                className="w-full rounded-lg border border-input bg-muted/40 pl-7 pr-2.5 py-1.5 text-foreground placeholder-muted-foreground focus:border-primary focus:outline-none"
              />
              <Search className="absolute left-2 top-2 h-3.5 w-3.5 text-muted-foreground" />
            </div>
          </div>
        </div>
      </div>

      {/* Main Content Area */}
      {loading ? (
        <div className="py-16 text-center text-xs text-muted-foreground">
          Discovering tech vacancies across Greenhouse & Remotive...
        </div>
      ) : jobs.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border bg-card/40 p-12 text-center backdrop-blur-md">
          <Briefcase className="mx-auto h-8 w-8 text-muted-foreground" />
          <h3 className="mt-3 text-sm font-semibold">No vacancies found</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            No listings matched your criteria. Trigger a job board crawl in Data Sources.
          </p>
        </div>
      ) : viewMode === "cards" ? (
        /* Cards View */
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {jobs.map((job) => (
            <div
              key={job.id}
              onClick={() => handleSelectJob(job.id)}
              className="group relative flex flex-col justify-between overflow-hidden rounded-xl border border-border bg-card/60 p-5 shadow-sm transition-all hover:border-primary/50 hover:bg-card/90 cursor-pointer backdrop-blur-md"
            >
              <div>
                <div className="flex items-start justify-between gap-2">
                  <div className="font-semibold text-sm text-foreground line-clamp-1 group-hover:text-primary transition-colors">
                    {job.title}
                  </div>
                  {formatRemoteBadge(job.remote_status)}
                </div>

                <div className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Building className="h-3.5 w-3.5 text-primary shrink-0" />
                  <span className="font-medium text-foreground">{job.company_name}</span>
                  {job.other_sources_count > 0 && (
                    <span className="rounded bg-primary/10 px-1.5 py-0.2 text-[10px] font-semibold text-primary" title="Unified across multiple platforms">
                      +{job.other_sources_count} platforms
                    </span>
                  )}
                </div>
                {isRemotiveJob(job) && (
                  <div className="mt-1 text-[10px] text-muted-foreground">
                    Listing via{" "}
                    <a href={job.application_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} className="font-medium text-primary hover:underline">
                      Remotive
                    </a>
                  </div>
                )}

                <div className="mt-2.5 flex items-center gap-1.5 text-[11px] text-muted-foreground">
                  <MapPin className="h-3 w-3 shrink-0" />
                  <span className="truncate">{job.location_text || "Worldwide / Remote"}</span>
                </div>

                {/* Tech Skills Pills */}
                {job.skills && job.skills.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1">
                    {job.skills.slice(0, 4).map((s) => (
                      <span
                        key={s.id}
                        className="rounded border border-border/80 bg-muted/40 px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground"
                      >
                        {s.skill_name}
                      </span>
                    ))}
                    {job.skills.length > 4 && (
                      <span className="rounded bg-muted/20 px-1.5 py-0.5 text-[10px] text-muted-foreground">
                        +{job.skills.length - 4}
                      </span>
                    )}
                  </div>
                )}
              </div>

              <div className="mt-5 flex items-center justify-between border-t border-border/60 pt-3 text-[11px] text-muted-foreground">
                <span className="capitalize">{job.experience_level.toLowerCase().replace("_", " ")}</span>
                <span className="text-primary font-medium group-hover:underline flex items-center gap-0.5">
                  View Role <ChevronRight className="h-3 w-3" />
                </span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        /* Table View */
        <div className="overflow-hidden rounded-xl border border-border bg-card/60 shadow-sm backdrop-blur-md">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-border bg-muted/30 text-muted-foreground">
                <tr>
                  <th className="px-5 py-3 font-semibold">Job Title & Company</th>
                  <th className="px-4 py-3 font-semibold">Category</th>
                  <th className="px-4 py-3 font-semibold">Location / Remote</th>
                  <th className="px-4 py-3 font-semibold">Seniority</th>
                  <th className="px-4 py-3 font-semibold">Key Skills</th>
                  <th className="px-5 py-3 text-right font-semibold">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {jobs.map((j) => (
                  <tr
                    key={j.id}
                    onClick={() => handleSelectJob(j.id)}
                    className="cursor-pointer transition-colors hover:bg-muted/30"
                  >
                    <td className="px-5 py-3.5">
                      <div className="font-semibold text-foreground">{j.title}</div>
                      <div className="text-[11px] text-muted-foreground">{j.company_name}</div>
                      {isRemotiveJob(j) && (
                  <div className="mt-1 text-[10px] text-muted-foreground">
                    Listing via{" "}
                    <a href={j.application_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} className="font-medium text-primary hover:underline">
                      Remotive
                    </a>
                  </div>
                )}
                    </td>
                    <td className="px-4 py-3.5">
                      <span className="rounded bg-muted px-2 py-0.5 text-[10px] font-semibold text-foreground">
                        {j.category.replace("_", " ")}
                      </span>
                    </td>
                    <td className="px-4 py-3.5">
                      <div className="flex items-center gap-1.5">
                        {formatRemoteBadge(j.remote_status)}
                        <span className="text-muted-foreground truncate max-w-[140px]">{j.location_text}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3.5 text-muted-foreground capitalize">
                      {j.experience_level.toLowerCase().replace("_", " ")}
                    </td>
                    <td className="px-4 py-3.5">
                      <div className="flex flex-wrap gap-1">
                        {j.skills.slice(0, 3).map((s) => (
                          <span key={s.id} className="rounded border border-border bg-muted/40 px-1.5 py-0.5 text-[10px]">
                            {s.skill_name}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-5 py-3.5 text-right">
                      <ChevronRight className="h-4 w-4 ml-auto text-muted-foreground" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Slide-over Job Detail Drawer */}
      {selectedJob && (
        <div className="fixed inset-y-0 right-0 z-50 flex w-full max-w-lg flex-col border-l border-border bg-card/95 p-6 shadow-2xl backdrop-blur-xl animate-in slide-in-from-right duration-200">
          <div className="flex items-start justify-between border-b border-border pb-4">
            <div>
              <h2 className="text-lg font-bold text-foreground leading-snug">{selectedJob.title}</h2>
              <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                <Building className="h-3.5 w-3.5 text-primary" />
                <span className="font-semibold text-foreground">{selectedJob.company_name}</span>
                <span>·</span>
                <span>{selectedJob.location_text || "Remote"}</span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <SaveButton entityType="JOB" entityId={selectedJob.id} />
              <button
                onClick={() => setSelectedJob(null)}
                className="rounded-lg p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto py-5 space-y-6 text-xs">
            {/* Quick Metrics Bar */}
            <div className="grid grid-cols-3 gap-2 text-center">
              <div className="rounded-lg border border-border bg-muted/20 p-2.5">
                <span className="text-[10px] text-muted-foreground">Category</span>
                <div className="font-semibold mt-0.5 truncate">{selectedJob.category.replace("_", " ")}</div>
              </div>
              <div className="rounded-lg border border-border bg-muted/20 p-2.5">
                <span className="text-[10px] text-muted-foreground">Seniority</span>
                <div className="font-semibold mt-0.5 capitalize">{selectedJob.experience_level.toLowerCase().replace("_", " ")}</div>
              </div>
              <div className="rounded-lg border border-border bg-muted/20 p-2.5">
                <span className="text-[10px] text-muted-foreground">Type</span>
                <div className="font-semibold mt-0.5 capitalize">{selectedJob.employment_type.toLowerCase().replace("_", " ")}</div>
              </div>
            </div>

            {/* In-Demand Skills */}
            {selectedJob.skills.length > 0 && (
              <div>
                <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
                  Required Technical Skills
                </span>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {selectedJob.skills.map((s) => (
                    <span
                      key={s.id}
                      className="rounded-full border border-primary/30 bg-primary/10 px-2.5 py-1 text-xs font-semibold text-primary"
                    >
                      {s.skill_name}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Description Body */}
            <div>
              <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
                Role Description & Requirements
              </span>
              <div
                className="mt-3 prose prose-invert max-w-none text-xs text-foreground/90 space-y-2 leading-relaxed"
                dangerouslySetInnerHTML={{ __html: selectedJob.description }}
              />
            </div>

            {/* Sighting & Provenance */}
            <div className="rounded-xl border border-border bg-muted/10 p-4 space-y-1.5 text-[11px] text-muted-foreground">
              <div className="flex justify-between">
                <span>Discovered:</span>
                <span>{formatDate(selectedJob.discovered_at)}</span>
              </div>
              <div className="flex justify-between">
                <span>Source Platform:</span>
                <span className="font-medium text-foreground">{selectedJob.source_platform}</span>
              </div>
              {isRemotiveJob(selectedJob) && (
                <div className="flex justify-between">
                  <span>Listing provided by:</span>
                  <a href={selectedJob.application_url} target="_blank" rel="noreferrer" className="font-medium text-primary hover:underline">
                    Remotive
                  </a>
                </div>
              )}
              {selectedJob.other_sources_count > 0 && (
                <div className="flex justify-between text-primary">
                  <span>Cross-Platform Dedup:</span>
                  <span>Unified across {selectedJob.other_sources_count + 1} boards</span>
                </div>
              )}
            </div>
          </div>

          {/* Action Footer */}
          <div className="border-t border-border pt-4">
            <a
              href={selectedJob.application_url}
              target="_blank"
              rel="noreferrer"
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-primary py-2.5 text-xs font-bold text-primary-foreground shadow hover:bg-primary/90"
            >
              <span>{isRemotiveJob(selectedJob) ? "View & apply on Remotive" : "Apply on Company Site"}</span>
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          </div>
        </div>
      )}
    </div>
  );
}
