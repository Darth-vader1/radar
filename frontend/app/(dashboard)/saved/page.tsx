"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Bookmark,
  Briefcase,
  Building2,
  CalendarDays,
  Download,
  ExternalLink,
  Loader2,
  Search,
  Tag,
  Trash2,
} from "lucide-react";
import { fetchApi } from "@/lib/api-client";
import { formatDate } from "@/lib/utils";

type EntityType = "BUSINESS" | "JOB" | "EVENT";

interface SavedRecord {
  id: string;
  entity_type: EntityType;
  entity_id: string;
  note: string | null;
  tags: string[];
  created_at: string;
  updated_at: string;
  entity: {
    title: string;
    subtitle: string | null;
    url: string | null;
    source: string | null;
    facts: Record<string, string | number | null>;
  } | null;
}

interface TagCount {
  tag: string;
  count: number;
}

const TYPE_TABS: { value: EntityType | ""; label: string }[] = [
  { value: "", label: "All" },
  { value: "BUSINESS", label: "Businesses" },
  { value: "JOB", label: "Jobs" },
  { value: "EVENT", label: "Events" },
];

const TYPE_ICON = { BUSINESS: Building2, JOB: Briefcase, EVENT: CalendarDays };
const TYPE_LABEL = { BUSINESS: "Business", JOB: "Job", EVENT: "Event" };

function factBadges(r: SavedRecord): string[] {
  const f = r.entity?.facts ?? {};
  const out: string[] = [];
  if (r.entity_type === "BUSINESS") {
    if (f.lead_score != null) out.push(`Lead score ${f.lead_score}`);
    if (f.phone) out.push(String(f.phone));
    if (f.email) out.push(String(f.email));
  } else if (r.entity_type === "JOB") {
    if (f.remote_status && f.remote_status !== "UNSPECIFIED") out.push(String(f.remote_status).toLowerCase());
    if (f.category) out.push(String(f.category).replace(/_/g, " ").toLowerCase());
    if (f.experience_level && f.experience_level !== "UNSPECIFIED") out.push(String(f.experience_level).toLowerCase());
  } else {
    if (f.status) out.push(String(f.status).replace(/_/g, " ").toLowerCase());
    if (f.registration_deadline) out.push(`Deadline ${formatDate(String(f.registration_deadline))}`);
    if (f.prize_summary) out.push(String(f.prize_summary));
  }
  return out;
}

function queryString(params: Record<string, string>): string {
  const parts = Object.entries(params).filter(([, v]) => v).map(([k, v]) => `${k}=${encodeURIComponent(v)}`);
  return parts.length ? `?${parts.join("&")}` : "";
}

export default function SavedRecordsPage() {
  const [records, setRecords] = useState<SavedRecord[]>([]);
  const [tags, setTags] = useState<TagCount[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [entityType, setEntityType] = useState<EntityType | "">("");
  const [activeTag, setActiveTag] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");

  const filters = { entity_type: entityType, tag: activeTag, q: search };

  const load = useCallback(async () => {
    setLoading(true);
    const [list, tagRes] = await Promise.all([
      fetchApi<SavedRecord[]>(`/saved${queryString({ entity_type: entityType, tag: activeTag, q: search })}`),
      fetchApi<TagCount[]>("/saved/tags"),
    ]);
    setError(list.error ?? null);
    setRecords(list.data ?? []);
    setTags(tagRes.data ?? []);
    setLoading(false);
  }, [entityType, activeTag, search]);

  useEffect(() => {
    load();
  }, [load]);

  const refreshTags = () => fetchApi<TagCount[]>("/saved/tags").then((t) => setTags(t.data ?? []));

  const replaceRecord = (updated: SavedRecord) => {
    setRecords((rs) => rs.map((r) => (r.id === updated.id ? updated : r)));
    refreshTags(); // tag chips reflect edits immediately
  };

  const removeRecord = async (id: string) => {
    const res = await fetchApi(`/saved/${id}`, { method: "DELETE" });
    if (res.status === 204 || res.status === 404) {
      setRecords((rs) => rs.filter((r) => r.id !== id));
      refreshTags();
    } else {
      setError(res.error || "Could not remove the record.");
    }
  };

  const hasFilters = Boolean(entityType || activeTag || search);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Saved Records</h1>
          <p className="text-sm text-muted-foreground">
            Your bookmarked businesses, jobs, and events, with your own notes and tags. Only you can see them.
          </p>
        </div>
        <a
          href={`/api/v1/saved/export.csv${queryString(filters)}`}
          className={`inline-flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-xs font-semibold hover:bg-muted ${
            records.length ? "" : "pointer-events-none opacity-50"
          }`}
          aria-disabled={!records.length}
        >
          <Download className="h-3.5 w-3.5" />
          Export CSV{hasFilters ? " (filtered)" : ""}
        </a>
      </div>

      {/* Filters */}
      <div className="space-y-3 rounded-xl border border-border bg-card/40 p-4 backdrop-blur-md">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex flex-wrap gap-1.5">
            {TYPE_TABS.map((t) => (
              <button
                key={t.label}
                onClick={() => setEntityType(t.value)}
                className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                  entityType === t.value ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setSearch(searchInput.trim());
            }}
            className="relative md:w-72"
          >
            <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Search titles, companies, notes…"
              className="w-full rounded-lg border border-input bg-muted/40 py-2 pl-9 pr-3 text-xs focus:border-primary focus:outline-none"
            />
          </form>
        </div>
        {tags.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <Tag className="h-3.5 w-3.5 text-muted-foreground" />
            {tags.map((t) => (
              <button
                key={t.tag}
                onClick={() => setActiveTag(activeTag === t.tag ? "" : t.tag)}
                className={`rounded-full border px-2.5 py-0.5 text-[11px] transition-colors ${
                  activeTag === t.tag
                    ? "border-amber-500/50 bg-amber-500/15 text-amber-300"
                    : "border-border text-muted-foreground hover:bg-muted"
                }`}
              >
                {t.tag} <span className="opacity-60">{t.count}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-2 text-xs text-destructive">
          <AlertTriangle className="h-4 w-4" />
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading saved records…
        </div>
      ) : records.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border bg-card/40 p-12 text-center backdrop-blur-md">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-amber-500/10 text-amber-400">
            <Bookmark className="h-6 w-6" />
          </div>
          <h3 className="mt-4 text-base font-semibold">{hasFilters ? "Nothing matches these filters" : "No saved records yet"}</h3>
          <p className="mx-auto mt-2 max-w-md text-xs text-muted-foreground">
            {hasFilters
              ? "Try a different type, tag, or search."
              : "Open any business, job, or event and press Save. It will appear here, ready for notes, tags and export."}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {records.map((r) => (
            <SavedCard key={r.id} record={r} onChange={replaceRecord} onRemove={() => removeRecord(r.id)} />
          ))}
        </div>
      )}
    </div>
  );
}

function SavedCard({
  record,
  onChange,
  onRemove,
}: {
  record: SavedRecord;
  onChange: (r: SavedRecord) => void;
  onRemove: () => void;
}) {
  const Icon = TYPE_ICON[record.entity_type];
  const [note, setNote] = useState(record.note ?? "");
  const [tagInput, setTagInput] = useState(record.tags.join(", "));
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState(false);

  const dirty = note !== (record.note ?? "") || tagInput !== record.tags.join(", ");

  const save = async () => {
    setSaving(true);
    setSaveError(null);
    const tags = tagInput.split(",").map((t) => t.trim()).filter(Boolean);
    const res = await fetchApi<SavedRecord>(`/saved/${record.id}`, {
      method: "PATCH",
      body: JSON.stringify({ note, tags }),
    });
    if (res.data) {
      onChange(res.data);
      setNote(res.data.note ?? "");
      setTagInput(res.data.tags.join(", "));
    } else {
      setSaveError(res.error || "Could not save changes.");
    }
    setSaving(false);
  };

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-border bg-card/60 p-5 backdrop-blur-md">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            <Icon className="h-3.5 w-3.5 text-primary" />
            {TYPE_LABEL[record.entity_type]}
            <span className="font-normal normal-case tracking-normal">· saved {formatDate(record.created_at)}</span>
          </div>
          {record.entity ? (
            <>
              <h3 className="mt-1 truncate text-sm font-semibold text-foreground" title={record.entity.title}>
                {record.entity.title}
              </h3>
              {record.entity.subtitle && (
                <p className="truncate text-xs text-muted-foreground">{record.entity.subtitle}</p>
              )}
            </>
          ) : (
            <h3 className="mt-1 flex items-center gap-1.5 text-sm font-semibold text-muted-foreground">
              <AlertTriangle className="h-4 w-4" /> No longer available in RADAR
            </h3>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {record.entity?.url && (
            <a
              href={record.entity.url}
              target="_blank"
              rel="noreferrer"
              title="Open"
              className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <ExternalLink className="h-4 w-4" />
            </a>
          )}
          {confirmRemove ? (
            <span className="flex items-center gap-1 text-[11px]">
              <button onClick={onRemove} className="rounded px-2 py-1 font-semibold text-destructive hover:bg-destructive/10">
                Remove
              </button>
              <button onClick={() => setConfirmRemove(false)} className="rounded px-2 py-1 text-muted-foreground hover:bg-muted">
                Cancel
              </button>
            </span>
          ) : (
            <button
              onClick={() => setConfirmRemove(true)}
              title="Remove from Saved Records"
              className="rounded-lg p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>

      {factBadges(record).length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {factBadges(record).map((b) => (
            <span key={b} className="rounded bg-muted px-2 py-0.5 text-[10px] font-medium capitalize text-foreground">
              {b}
            </span>
          ))}
        </div>
      )}

      <textarea
        value={note}
        onChange={(e) => setNote(e.target.value)}
        maxLength={2000}
        rows={2}
        placeholder="Add a note…"
        className="w-full resize-y rounded-lg border border-input bg-muted/30 px-3 py-2 text-xs focus:border-primary focus:outline-none"
      />
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Tag className="absolute left-2.5 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" />
          <input
            value={tagInput}
            onChange={(e) => setTagInput(e.target.value)}
            placeholder="Tags, comma separated"
            className="w-full rounded-lg border border-input bg-muted/30 py-1.5 pl-7 pr-2 text-[11px] focus:border-primary focus:outline-none"
          />
        </div>
        <button
          onClick={save}
          disabled={!dirty || saving}
          className="rounded-lg bg-primary px-3 py-1.5 text-[11px] font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
        >
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
      {saveError && <p className="text-[11px] text-destructive">{saveError}</p>}
    </div>
  );
}
