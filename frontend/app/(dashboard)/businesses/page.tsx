"use client";

import { useEffect, useState } from "react";
import {
  Building2,
  Search,
  Filter,
  RefreshCw,
  Globe,
  Mail,
  Phone,
  ExternalLink,
  ChevronRight,
  X,
  Sliders,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  HelpCircle,
  Instagram,
  Facebook,
  Linkedin,
  Flame,
} from "lucide-react";
import { fetchApi } from "@/lib/api-client";
import { SaveButton } from "@/components/save-button";
import { useLatest } from "@/lib/use-latest";
import { isOsmRecord, OSM_COPYRIGHT_URL } from "@/lib/attribution";
import { formatDate } from "@/lib/utils";

interface BusinessItem {
  id: string;
  name: string;
  category: string | null;
  subcategory: string | null;
  phone_number: string | null;
  phone_verification_status: string;
  public_email: string | null;
  email_verification_status: string;
  website_url: string | null;
  website_status: string;
  has_online_ordering: boolean | null;
  online_presence: string;
  physical_address: string | null;
  city: string | null;
  state: string | null;
  country: string;
  latitude: number | null;
  longitude: number | null;
  original_source_url: string;
  lead_score: number;
  lead_score_explanation: {
    rule_key: string;
    label: string;
    points: number;
    reason: string;
  }[];
  discovered_at: string;
  last_verified_at: string | null;
}

interface ScoringRule {
  id: string;
  rule_key: string;
  label: string;
  points: number;
  is_enabled: boolean;
}

export default function BusinessesPage() {
  const [businesses, setBusinesses] = useState<BusinessItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedBiz, setSelectedBiz] = useState<BusinessItem | null>(null);

  // Filters
  const [city, setCity] = useState("Ikeja");
  const [category, setCategory] = useState("");
  const [websiteStatus, setWebsiteStatus] = useState("");
  const [minLeadScore, setMinLeadScore] = useState<number>(0);
  const [search, setSearch] = useState("");

  // Scoring Rules Modal
  const [showRulesModal, setShowRulesModal] = useState(false);
  const [scoringRules, setScoringRules] = useState<ScoringRule[]>([]);
  const [rulesLoading, setRulesLoading] = useState(false);

  const loadBusinesses = async () => {
    setLoading(true);
    const queryParts = [];
    if (city) queryParts.push(`city=${encodeURIComponent(city)}`);
    if (category) queryParts.push(`category=${encodeURIComponent(category)}`);
    if (websiteStatus) queryParts.push(`website_status=${encodeURIComponent(websiteStatus)}`);
    if (minLeadScore > 0) queryParts.push(`min_lead_score=${minLeadScore}`);
    if (search) queryParts.push(`search=${encodeURIComponent(search)}`);

    const queryStr = queryParts.length ? `?${queryParts.join("&")}` : "";
    const res = await fetchApi<BusinessItem[]>(`/businesses${queryStr}`);
    if (res.data) {
      setBusinesses(res.data);
    }
    setLoading(false);
  };

  const loadScoringRules = async () => {
    setRulesLoading(true);
    const res = await fetchApi<ScoringRule[]>("/businesses/scoring-rules");
    if (res.data) {
      setScoringRules(res.data);
    }
    setRulesLoading(false);
  };

  // Dropdown filters re-fetch immediately; text search re-fetches on Enter/submit.
  const loadBusinessesRef = useLatest(loadBusinesses);
  useEffect(() => {
    loadBusinessesRef.current();
  }, [city, websiteStatus, minLeadScore, loadBusinessesRef]);

  const handleUpdateRulePoints = async (ruleKey: string, newPoints: number) => {
    const res = await fetchApi(`/businesses/scoring-rules/${ruleKey}`, {
      method: "PATCH",
      body: JSON.stringify({ points: newPoints }),
    });
    if (res.data) {
      loadScoringRules();
      loadBusinesses();
    }
  };

  const getWebsiteBadge = (status: string, url: string | null) => {
    switch (status) {
      case "HAS_WEBSITE":
        return (
          <a
            href={url || "#"}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="inline-flex items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-400 hover:underline"
          >
            <Globe className="h-3 w-3" /> Has Website
          </a>
        );
      case "NO_WEBSITE_FOUND":
        return (
          <span className="inline-flex items-center gap-1 rounded-full border border-red-500/30 bg-red-500/10 px-2 py-0.5 text-[11px] font-medium text-red-400">
            <XCircle className="h-3 w-3" /> No Website Found
          </span>
        );
      case "WEBSITE_BROKEN":
        return (
          <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-400">
            <AlertTriangle className="h-3 w-3" /> Website Broken
          </span>
        );
      case "WEBSITE_UNREACHABLE":
        return (
          <span className="inline-flex items-center gap-1 rounded-full border border-border bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
            <XCircle className="h-3 w-3" /> Unreachable
          </span>
        );
      case "WEBSITE_REDIRECTS_INCORRECTLY":
        return (
          <span className="inline-flex items-center gap-1 rounded-full border border-purple-500/30 bg-purple-500/10 px-2 py-0.5 text-[11px] font-medium text-purple-400">
            <AlertTriangle className="h-3 w-3" /> Redirects Incorrectly
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 rounded-full border border-border bg-muted/40 px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
            <HelpCircle className="h-3 w-3" /> Manual Verification
          </span>
        );
    }
  };

  const getLeadScoreBadge = (score: number) => {
    let color = "text-muted-foreground border-border bg-muted/40";
    if (score >= 70) {
      color = "text-emerald-400 border-emerald-500/30 bg-emerald-500/10 font-bold";
    } else if (score >= 40) {
      color = "text-amber-400 border-amber-500/30 bg-amber-500/10 font-bold";
    }

    return (
      <div className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs ${color}`}>
        <Flame className="h-3 w-3" />
        <span>{score}/100</span>
      </div>
    );
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">BusinessRadar</h1>
          <p className="text-sm text-muted-foreground">
            Commercial POI & SME discovery, verified contact channels, and lead opportunity scoring.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => {
              setShowRulesModal(true);
              loadScoringRules();
            }}
            className="flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-2 text-xs font-medium text-foreground hover:bg-muted"
          >
            <Sliders className="h-3.5 w-3.5" />
            Scoring Weights
          </button>
          <button
            onClick={loadBusinesses}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>
        </div>
      </div>

      {/* Multi-facet Filter Bar */}
      <div className="rounded-xl border border-border bg-card/60 p-4 shadow-sm backdrop-blur-md space-y-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5 text-xs">
          {/* City */}
          <div>
            <label className="block text-[11px] font-medium text-muted-foreground mb-1">City</label>
            <select
              value={city}
              onChange={(e) => setCity(e.target.value)}
              className="w-full rounded-lg border border-input bg-muted/40 px-2.5 py-1.5 text-foreground focus:border-primary focus:outline-none"
            >
              <option value="Ikeja">Ikeja (Lagos State)</option>
              <option value="Lagos">Lagos / Victoria Island</option>
              <option value="Abuja">Abuja Central</option>
              <option value="Port Harcourt">Port Harcourt</option>
              <option value="Ibadan">Ibadan</option>
            </select>
          </div>

          {/* Website Status */}
          <div>
            <label className="block text-[11px] font-medium text-muted-foreground mb-1">Website Availability</label>
            <select
              value={websiteStatus}
              onChange={(e) => setWebsiteStatus(e.target.value)}
              className="w-full rounded-lg border border-input bg-muted/40 px-2.5 py-1.5 text-foreground focus:border-primary focus:outline-none"
            >
              <option value="">All Statuses</option>
              <option value="NO_WEBSITE_FOUND">No Website Found (High Opportunity)</option>
              <option value="HAS_WEBSITE">Has Website</option>
              <option value="WEBSITE_BROKEN">Website Broken</option>
              <option value="WEBSITE_UNREACHABLE">Website Unreachable</option>
              <option value="WEBSITE_REQUIRES_MANUAL_VERIFICATION">Requires Verification</option>
            </select>
          </div>

          {/* Min Lead Score */}
          <div>
            <label className="block text-[11px] font-medium text-muted-foreground mb-1">
              Min Lead Score: <span className="font-bold text-foreground">{minLeadScore}/100</span>
            </label>
            <input
              type="range"
              min="0"
              max="90"
              step="10"
              value={minLeadScore}
              onChange={(e) => setMinLeadScore(Number(e.target.value))}
              className="w-full accent-primary mt-1"
            />
          </div>

          {/* Category Search */}
          <div>
            <label className="block text-[11px] font-medium text-muted-foreground mb-1">Category Filter</label>
            <input
              type="text"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && loadBusinesses()}
              placeholder="e.g. Restaurants, Pharmacy"
              className="w-full rounded-lg border border-input bg-muted/40 px-2.5 py-1.5 text-foreground placeholder-muted-foreground focus:border-primary focus:outline-none"
            />
          </div>

          {/* Keyword Search */}
          <div>
            <label className="block text-[11px] font-medium text-muted-foreground mb-1">Keyword Search</label>
            <div className="relative">
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && loadBusinesses()}
                placeholder="Search business name..."
                className="w-full rounded-lg border border-input bg-muted/40 pl-7 pr-2.5 py-1.5 text-foreground placeholder-muted-foreground focus:border-primary focus:outline-none"
              />
              <Search className="absolute left-2 top-2 h-3.5 w-3.5 text-muted-foreground" />
            </div>
          </div>
        </div>
      </div>

      {/* Businesses Table */}
      <div className="overflow-hidden rounded-xl border border-border bg-card/60 shadow-sm backdrop-blur-md">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-border bg-muted/30 text-muted-foreground">
              <tr>
                <th className="px-5 py-3 font-semibold">Business Name</th>
                <th className="px-4 py-3 font-semibold">Category</th>
                <th className="px-4 py-3 font-semibold">Location</th>
                <th className="px-4 py-3 font-semibold">Website Availability</th>
                <th className="px-4 py-3 font-semibold">Direct Contacts</th>
                <th className="px-4 py-3 font-semibold">Lead Score</th>
                <th className="px-5 py-3 text-right font-semibold">Inspect</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {loading ? (
                <tr>
                  <td colSpan={7} className="px-5 py-8 text-center text-muted-foreground">
                    Discovering businesses in {city}...
                  </td>
                </tr>
              ) : businesses.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-5 py-8 text-center text-muted-foreground">
                    No businesses matched your search filters. Trigger an OpenStreetMap crawl for {city} in Data Sources.
                  </td>
                </tr>
              ) : (
                businesses.map((b) => (
                  <tr
                    key={b.id}
                    onClick={() => setSelectedBiz(b)}
                    className="cursor-pointer transition-colors hover:bg-muted/30"
                  >
                    <td className="px-5 py-3.5 font-semibold text-foreground">
                      <div className="flex items-center gap-2">
                        <Building2 className="h-4 w-4 text-primary shrink-0" />
                        <span>{b.name}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3.5">
                      <span className="rounded bg-muted px-2 py-0.5 text-[10px] font-semibold text-foreground">
                        {b.category || "General Commercial"}
                      </span>
                    </td>
                    <td className="px-4 py-3.5 text-muted-foreground">
                      {b.city || "Lagos"}, {b.country}
                    </td>
                    <td className="px-4 py-3.5">
                      {getWebsiteBadge(b.website_status, b.website_url)}
                    </td>
                    <td className="px-4 py-3.5">
                      <div className="flex items-center gap-2 text-muted-foreground">
                        {b.public_email ? (
                          <span title={b.public_email} className="flex items-center gap-1 text-emerald-400">
                            <Mail className="h-3.5 w-3.5" />
                          </span>
                        ) : (
                          <span title="No email discovered" className="opacity-30">
                            <Mail className="h-3.5 w-3.5" />
                          </span>
                        )}
                        {b.phone_number ? (
                          <span title={b.phone_number} className="flex items-center gap-1 text-blue-400">
                            <Phone className="h-3.5 w-3.5" />
                          </span>
                        ) : (
                          <span title="No phone discovered" className="opacity-30">
                            <Phone className="h-3.5 w-3.5" />
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3.5">
                      {getLeadScoreBadge(b.lead_score)}
                    </td>
                    <td className="px-5 py-3.5 text-right text-muted-foreground">
                      <ChevronRight className="h-4 w-4 ml-auto" />
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        {businesses.some(isOsmRecord) && (
          <div className="border-t border-border/60 px-5 py-2 text-[10px] text-muted-foreground">
            Business data includes information ©{" "}
            <a href={OSM_COPYRIGHT_URL} target="_blank" rel="noreferrer" className="text-primary hover:underline">
              OpenStreetMap contributors
            </a>
            , available under the Open Database License.
          </div>
        )}
      </div>

      {/* Slide-over Detail Drawer */}
      {selectedBiz && (
        <div className="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col border-l border-border bg-card/95 p-6 shadow-2xl backdrop-blur-xl animate-in slide-in-from-right duration-200">
          <div className="flex items-start justify-between border-b border-border pb-4">
            <div>
              <div className="flex items-center gap-2">
                <Building2 className="h-5 w-5 text-primary" />
                <h2 className="text-lg font-bold text-foreground">{selectedBiz.name}</h2>
              </div>
              <p className="text-xs text-muted-foreground mt-0.5">
                {selectedBiz.category || "Commercial"} · {selectedBiz.city}, {selectedBiz.country}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <SaveButton entityType="BUSINESS" entityId={selectedBiz.id} />
              <button
                onClick={() => setSelectedBiz(null)}
                className="rounded-lg p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto py-5 space-y-6 text-xs">
            {/* Lead Score Card */}
            <div className="rounded-xl border border-primary/30 bg-primary/5 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-primary">Sales Opportunity Score</span>
                <span className="text-xl font-black text-primary">{selectedBiz.lead_score}/100</span>
              </div>

              <div className="space-y-1.5 border-t border-primary/20 pt-2">
                {selectedBiz.lead_score_explanation.length > 0 ? (
                  selectedBiz.lead_score_explanation.map((item, idx) => (
                    <div key={idx} className="flex items-center justify-between text-[11px]">
                      <span className="text-muted-foreground">{item.label}</span>
                      <span className="font-mono font-bold text-emerald-400">+{item.points}</span>
                    </div>
                  ))
                ) : (
                  <span className="text-[11px] text-muted-foreground">Baseline scoring factors evaluated.</span>
                )}
              </div>
            </div>

            {/* Website Status & Presence */}
            <div className="rounded-xl border border-border bg-muted/20 p-4 space-y-2">
              <span className="font-semibold text-muted-foreground uppercase tracking-wider text-[10px]">
                Website & Online Presence
              </span>
              <div className="mt-1 flex items-center justify-between">
                <span>Website Status:</span>
                <div>{getWebsiteBadge(selectedBiz.website_status, selectedBiz.website_url)}</div>
              </div>
              {selectedBiz.website_url && (
                <div className="flex items-center justify-between pt-1">
                  <span className="text-muted-foreground">Target URL:</span>
                  <a
                    href={selectedBiz.website_url}
                    target="_blank"
                    rel="noreferrer"
                    className="flex items-center gap-1 font-mono text-[11px] text-primary hover:underline"
                  >
                    {selectedBiz.website_url.replace(/^https?:\/\//, "").slice(0, 30)}
                    <ExternalLink className="h-3 w-3" />
                  </a>
                </div>
              )}
              <div className="flex items-center justify-between pt-1">
                <span className="text-muted-foreground">Online Ordering:</span>
                <span className="font-medium">
                  {selectedBiz.has_online_ordering ? "Detected" : "None Detected"}
                </span>
              </div>
            </div>

            {/* Contact Channels */}
            <div className="rounded-xl border border-border bg-muted/20 p-4 space-y-2.5">
              <span className="font-semibold text-muted-foreground uppercase tracking-wider text-[10px]">
                Verified Contact Channels
              </span>

              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Public Email:</span>
                {selectedBiz.public_email ? (
                  <a
                    href={`mailto:${selectedBiz.public_email}`}
                    className="font-medium text-emerald-400 hover:underline"
                  >
                    {selectedBiz.public_email}
                  </a>
                ) : (
                  <span className="text-muted-foreground italic">No public email found</span>
                )}
              </div>

              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Phone Number:</span>
                {selectedBiz.phone_number ? (
                  <a
                    href={`tel:${selectedBiz.phone_number}`}
                    className="font-medium text-blue-400 hover:underline"
                  >
                    {selectedBiz.phone_number}
                  </a>
                ) : (
                  <span className="text-muted-foreground italic">No phone found</span>
                )}
              </div>

              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Physical Address:</span>
                <span className="text-right max-w-xs text-foreground">
                  {selectedBiz.physical_address || `${selectedBiz.city}, ${selectedBiz.country}`}
                </span>
              </div>
            </div>

            {/* Provenance Attribution */}
            <div className="rounded-xl border border-border bg-muted/10 p-4 space-y-1.5 text-[11px]">
              <span className="font-semibold text-muted-foreground uppercase tracking-wider text-[10px]">
                Data Provenance
              </span>
              <div className="flex justify-between">
                <span className="text-muted-foreground">First Discovered:</span>
                <span>{formatDate(selectedBiz.discovered_at)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Source URL:</span>
                <a
                  href={selectedBiz.original_source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-primary hover:underline truncate max-w-[200px]"
                >
                  {selectedBiz.original_source_url}
                </a>
              </div>
              {isOsmRecord(selectedBiz) && (
                <div className="text-[10px] text-muted-foreground">
                  Data ©{" "}
                  <a href={OSM_COPYRIGHT_URL} target="_blank" rel="noreferrer" className="text-primary hover:underline">
                    OpenStreetMap contributors
                  </a>{" "}
                  (ODbL)
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Scoring Configuration Modal */}
      {showRulesModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-xl border border-border bg-card p-6 shadow-2xl">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <div>
                <h3 className="text-base font-bold">Configure Lead Scoring Rules</h3>
                <p className="text-xs text-muted-foreground">Adjust point values assigned to sales opportunity indicators.</p>
              </div>
              <button
                onClick={() => setShowRulesModal(false)}
                className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="mt-4 space-y-3">
              {rulesLoading ? (
                <div className="py-6 text-center text-xs text-muted-foreground">Loading scoring rules...</div>
              ) : (
                scoringRules.map((r) => (
                  <div key={r.id} className="flex items-center justify-between rounded-lg border border-border bg-muted/20 p-3 text-xs">
                    <div>
                      <div className="font-semibold text-foreground">{r.label}</div>
                      <div className="font-mono text-[10px] text-muted-foreground">{r.rule_key}</div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-primary">+{r.points} pts</span>
                      <input
                        type="number"
                        min="0"
                        max="50"
                        value={r.points}
                        onChange={(e) => handleUpdateRulePoints(r.rule_key, Number(e.target.value))}
                        className="w-16 rounded border border-input bg-card px-2 py-1 text-right text-xs"
                      />
                    </div>
                  </div>
                ))
              )}
            </div>

            <div className="mt-6 flex justify-end">
              <button
                onClick={() => setShowRulesModal(false)}
                className="rounded-lg bg-primary px-4 py-2 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
