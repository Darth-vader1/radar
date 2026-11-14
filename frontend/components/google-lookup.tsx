"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, ExternalLink, Globe, Loader2, MapPin, Phone, Search, Star } from "lucide-react";
import { fetchApi } from "@/lib/api-client";

interface GoogleDetails {
  place_id: string;
  matched_by: "place_id" | "search";
  name: string | null;
  address: string | null;
  phone: string | null;
  international_phone: string | null;
  website: string | null;
  google_maps_url: string | null;
  rating: number | null;
  rating_count: number | null;
  business_status: string | null;
  category: string | null;
  opening_hours: string[];
  attribution: string;
}

const STATUS_TEXT: Record<string, string> = {
  CLOSED_TEMPORARILY: "Temporarily closed",
  CLOSED_PERMANENTLY: "Permanently closed",
};

/**
 * "Look up on Google": fetches current Google Maps details when clicked. Shown only, never saved
 * (Google's terms allow storing just the place ID). Each click is a paid Google request.
 */
export function GoogleLookup({ businessId }: { businessId: string }) {
  const [details, setDetails] = useState<GoogleDetails | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A different business: clear the previous result.
  useEffect(() => {
    setDetails(null);
    setError(null);
  }, [businessId]);

  const lookUp = async () => {
    setLoading(true);
    setError(null);
    const res = await fetchApi<GoogleDetails>(`/businesses/${businessId}/google`);
    setLoading(false);
    if (res.data) setDetails(res.data);
    else if (res.status === 403) setError("Google lookups need the researcher role or higher.");
    else setError(res.error ?? "Google lookup failed.");
  };

  if (!details) {
    return (
      <div className="rounded-xl border border-border bg-muted/20 p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="font-semibold">Google Maps details</div>
            <p className="text-[11px] text-muted-foreground">Current phone, website, rating and hours. Shown, not saved.</p>
          </div>
          <button
            type="button"
            onClick={lookUp}
            disabled={loading}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium hover:bg-muted disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Search className="h-3.5 w-3.5" />}
            Look up on Google
          </button>
        </div>
        {error && (
          <p role="alert" className="mt-2 flex items-center gap-1.5 text-[11px] text-red-400">
            <AlertTriangle className="h-3.5 w-3.5" /> {error}
          </p>
        )}
      </div>
    );
  }

  const status = details.business_status ? STATUS_TEXT[details.business_status] : null;
  return (
    <div className="space-y-3 rounded-xl border border-border bg-muted/20 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-semibold">{details.name ?? "Google Maps details"}</div>
          {details.category && <div className="text-[11px] text-muted-foreground">{details.category}</div>}
        </div>
        {details.rating != null && (
          <span className="inline-flex shrink-0 items-center gap-1 text-[11px]">
            <Star className="h-3.5 w-3.5 fill-amber-400 text-amber-400" />
            {details.rating.toFixed(1)}
            {details.rating_count != null && <span className="text-muted-foreground">({details.rating_count.toLocaleString()})</span>}
          </span>
        )}
      </div>

      {details.matched_by === "search" && (
        <p className="text-[11px] text-amber-400">Matched by name. Check this is the right place.</p>
      )}
      {status && <p className="text-[11px] font-semibold text-red-400">{status}</p>}

      <dl className="space-y-1.5">
        {details.phone && (
          <div className="flex items-center gap-2">
            <Phone className="h-3.5 w-3.5 text-muted-foreground" />
            <a href={`tel:${details.international_phone ?? details.phone}`} className="hover:text-primary">{details.phone}</a>
          </div>
        )}
        {details.website && (
          <div className="flex items-center gap-2">
            <Globe className="h-3.5 w-3.5 text-muted-foreground" />
            <a href={details.website} target="_blank" rel="noopener noreferrer" className="truncate text-primary hover:underline">
              {details.website.replace(/^https?:\/\//, "").replace(/\/$/, "")}
            </a>
          </div>
        )}
        {details.address && (
          <div className="flex items-start gap-2">
            <MapPin className="mt-0.5 h-3.5 w-3.5 text-muted-foreground" />
            <span>{details.address}</span>
          </div>
        )}
        {!details.phone && !details.website && <p className="text-[11px] text-muted-foreground">Google lists no phone or website.</p>}
      </dl>

      {details.opening_hours.length > 0 && (
        <details className="text-[11px]">
          <summary className="cursor-pointer text-muted-foreground hover:text-foreground">Opening hours</summary>
          <ul className="mt-1 space-y-0.5 pl-1">
            {details.opening_hours.map((h) => <li key={h}>{h}</li>)}
          </ul>
        </details>
      )}

      <div className="flex items-center justify-between border-t border-border/60 pt-2 text-[10px] text-muted-foreground">
        <span>Data from {details.attribution}. Not saved.</span>
        {details.google_maps_url && (
          <a href={details.google_maps_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-primary hover:underline">
            View on Google Maps <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>
    </div>
  );
}
