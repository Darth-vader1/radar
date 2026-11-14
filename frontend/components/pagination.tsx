import { ChevronLeft, ChevronRight } from "lucide-react";

export const PAGE_SIZE = 50;

/** "Showing 51–100 of 2,047" with Previous / Next. Renders nothing until the total is known. */
export function Pagination({
  total,
  offset,
  pageSize = PAGE_SIZE,
  onChange,
  noun = "results",
}: {
  total: number | undefined;
  offset: number;
  pageSize?: number;
  onChange: (offset: number) => void;
  noun?: string;
}) {
  if (total === undefined) return null;
  if (total === 0) return null;
  const from = offset + 1;
  const to = Math.min(offset + pageSize, total);
  const page = Math.floor(offset / pageSize) + 1;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const button =
    "inline-flex items-center gap-1 rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs font-medium hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40";
  return (
    <nav aria-label="Pagination" className="flex flex-wrap items-center justify-between gap-3 px-1 py-2 text-xs text-muted-foreground">
      <span>
        Showing <span className="font-medium text-foreground tabular-nums">{from.toLocaleString()}–{to.toLocaleString()}</span> of{" "}
        <span className="font-medium text-foreground tabular-nums">{total.toLocaleString()}</span> {noun}
      </span>
      {pages > 1 && (
        <div className="flex items-center gap-2">
          <button type="button" className={button} disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - pageSize))}>
            <ChevronLeft className="h-3.5 w-3.5" /> Previous
          </button>
          <span className="tabular-nums">Page {page} of {pages.toLocaleString()}</span>
          <button type="button" className={button} disabled={to >= total} onClick={() => onChange(offset + pageSize)}>
            Next <ChevronRight className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
    </nav>
  );
}
