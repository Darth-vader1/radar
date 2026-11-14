"use client";

import { useEffect, useState } from "react";
import { Bookmark, BookmarkCheck, Loader2 } from "lucide-react";
import { fetchApi } from "@/lib/api-client";

export type SavedEntityType = "BUSINESS" | "JOB" | "EVENT";

interface SavedRecordRef {
  id: string;
}

/**
 * Save / unsave toggle for a business, job or event. Saved items appear on the
 * Saved Records page, where notes and tags can be added.
 */
export function SaveButton({ entityType, entityId }: { entityType: SavedEntityType; entityId: string }) {
  const [savedId, setSavedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchApi<SavedRecordRef>(`/saved/by-entity/${entityType}/${entityId}`).then((res) => {
      if (cancelled) return;
      setSavedId(res.data?.id ?? null); // 404 simply means "not saved yet"
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [entityType, entityId]);

  const toggle = async () => {
    setBusy(true);
    setError(null);
    if (savedId) {
      const res = await fetchApi(`/saved/${savedId}`, { method: "DELETE" });
      if (res.status === 204 || res.status === 404) setSavedId(null);
      else setError(res.error || "Could not remove.");
    } else {
      const res = await fetchApi<SavedRecordRef>("/saved", {
        method: "POST",
        body: JSON.stringify({ entity_type: entityType, entity_id: entityId }),
      });
      if (res.data?.id) setSavedId(res.data.id);
      else setError(res.error || "Could not save.");
    }
    setBusy(false);
  };

  const saved = Boolean(savedId);
  return (
    <button
      type="button"
      onClick={toggle}
      disabled={loading || busy}
      title={error ?? (saved ? "Remove from Saved Records" : "Save to Saved Records")}
      aria-pressed={saved}
      className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-semibold transition-colors disabled:opacity-60 ${
        saved
          ? "border-amber-500/40 bg-amber-500/10 text-amber-400 hover:bg-amber-500/20"
          : "border-border text-muted-foreground hover:bg-muted hover:text-foreground"
      } ${error ? "border-destructive/60 text-destructive" : ""}`}
    >
      {loading || busy ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      ) : saved ? (
        <BookmarkCheck className="h-3.5 w-3.5" />
      ) : (
        <Bookmark className="h-3.5 w-3.5" />
      )}
      <span>{error ? "Retry" : saved ? "Saved" : "Save"}</span>
    </button>
  );
}
