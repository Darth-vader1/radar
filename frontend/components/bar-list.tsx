export interface NamedCount {
  name: string;
  count: number;
}

/** Single-series horizontal bars: one hue, value labels in text ink, hover shows the share. */
export function BarList({ items, total, unit }: { items: NamedCount[]; total?: number; unit: string }) {
  if (!items.length) return <p className="text-xs text-muted-foreground">No data yet.</p>;
  const max = Math.max(...items.map((i) => i.count));
  return (
    <ul className="space-y-2.5">
      {items.map((i) => {
        const share = total ? ` · ${Math.round((100 * i.count) / total)}% of ${total.toLocaleString()}` : "";
        return (
          <li key={i.name} title={`${i.name}: ${i.count.toLocaleString()} ${unit}${share}`} className="group">
            <div className="flex items-baseline justify-between gap-3 text-xs">
              <span className="truncate">{i.name}</span>
              <span className="tabular-nums text-muted-foreground">{i.count.toLocaleString()}</span>
            </div>
            <div className="mt-1 h-1.5 w-full rounded-full bg-muted/40">
              <div
                className="h-1.5 rounded-full bg-primary/80 transition-colors group-hover:bg-primary"
                style={{ width: `${Math.max(2, (100 * i.count) / max)}%` }}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

export function Panel({ title, subtitle, children, className = "" }: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-xl border border-border bg-card/60 p-5 backdrop-blur-md ${className}`}>
      <h2 className="text-sm font-semibold">{title}</h2>
      {subtitle && <p className="text-[11px] text-muted-foreground">{subtitle}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}
