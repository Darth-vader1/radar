"use client";

import { Bookmark } from "lucide-react";

export default function SavedRecordsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Saved Records</h1>
        <p className="text-sm text-muted-foreground">Bookmarked businesses, jobs, and events across discovery modules.</p>
      </div>

      <div className="rounded-xl border border-dashed border-border bg-card/40 p-12 text-center backdrop-blur-md">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-amber-500/10 text-amber-400">
          <Bookmark className="h-6 w-6" />
        </div>
        <h3 className="mt-4 text-base font-semibold">User Bookmarks (Phase 7)</h3>
        <p className="mx-auto mt-2 max-w-md text-xs text-muted-foreground">
          Allows tagging, custom notes, search alerts, and targeted export batches for curated records.
        </p>
      </div>
    </div>
  );
}
