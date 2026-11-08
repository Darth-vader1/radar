"use client";

import { useEffect, useState } from "react";
import { Key, Plus, Trash2, Copy, Check, ShieldCheck, User } from "lucide-react";
import { fetchApi } from "@/lib/api-client";
import { getStoredUser, UserProfile } from "@/lib/auth";
import { formatDate } from "@/lib/utils";

interface ApiKeyItem {
  id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  rate_limit_per_minute: number;
  created_at: string;
  last_used_at: string | null;
}

export default function SettingsPage() {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [keys, setKeys] = useState<ApiKeyItem[]>([]);
  const [newKeyName, setNewKeyName] = useState("");
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [loading, setLoading] = useState(false);

  const loadKeys = async () => {
    const res = await fetchApi<ApiKeyItem[]>("/auth/api-keys");
    if (res.data) {
      setKeys(res.data);
    }
  };

  useEffect(() => {
    setUser(getStoredUser());
    loadKeys();
  }, []);

  const handleCreateKey = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newKeyName.trim()) return;
    setLoading(true);

    const res = await fetchApi("/auth/api-keys", {
      method: "POST",
      body: JSON.stringify({
        name: newKeyName.trim(),
        scopes: ["read", "write"],
        rate_limit_per_minute: 60,
      }),
    });

    if (res.data) {
      setCreatedKey(res.data.raw_api_key);
      setNewKeyName("");
      loadKeys();
    }
    setLoading(false);
  };

  const handleRevokeKey = async (id: string) => {
    await fetchApi(`/auth/api-keys/${id}`, { method: "DELETE" });
    loadKeys();
  };

  const copyToClipboard = () => {
    if (!createdKey) return;
    navigator.clipboard.writeText(createdKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 3000);
  };

  return (
    <div className="space-y-8 max-w-4xl">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Platform Settings & Security</h1>
        <p className="text-sm text-muted-foreground">Manage API keys, operator access control, and credentials.</p>
      </div>

      {/* Operator Profile Card */}
      <div className="rounded-xl border border-border bg-card/60 p-6 shadow-sm backdrop-blur-md">
        <h2 className="text-base font-semibold flex items-center gap-2">
          <User className="h-4 w-4 text-primary" />
          Operator Profile
        </h2>
        <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
          <div>
            <span className="text-muted-foreground">Account Email</span>
            <div className="font-semibold text-foreground mt-0.5">{user?.email || "Operator"}</div>
          </div>
          <div>
            <span className="text-muted-foreground">Assigned Roles</span>
            <div className="flex items-center gap-1.5 mt-0.5">
              <ShieldCheck className="h-3.5 w-3.5 text-primary" />
              <span className="font-semibold text-foreground capitalize">
                {user?.roles?.map((r) => r.name.replace("_", " ")).join(", ") || "Standard User"}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* API Key Management */}
      <div className="rounded-xl border border-border bg-card/60 p-6 shadow-sm backdrop-blur-md space-y-6">
        <div>
          <h2 className="text-base font-semibold flex items-center gap-2">
            <Key className="h-4 w-4 text-primary" />
            Programmatic API Keys
          </h2>
          <p className="text-xs text-muted-foreground mt-1">
            Generate scoped API keys for external integrations, SDKs, or automated pipelines.
          </p>
        </div>

        {/* Create Key Form */}
        <form onSubmit={handleCreateKey} className="flex gap-3">
          <input
            type="text"
            required
            value={newKeyName}
            onChange={(e) => setNewKeyName(e.target.value)}
            placeholder="e.g. Production Data Ingestion Worker"
            className="flex-1 rounded-lg border border-input bg-muted/40 px-3 py-2 text-xs text-foreground placeholder-muted-foreground focus:border-primary focus:outline-none"
          />
          <button
            type="submit"
            disabled={loading}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-xs font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            <Plus className="h-3.5 w-3.5" />
            Generate Key
          </button>
        </form>

        {/* Modal / Banner for newly created key */}
        {createdKey && (
          <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-xs space-y-2">
            <div className="font-semibold text-amber-400">Save Your Secret Key Now</div>
            <p className="text-[11px] text-muted-foreground">
              This secret key will never be displayed again. Store it securely in your deployment environment.
            </p>
            <div className="flex items-center gap-2">
              <code className="flex-1 rounded bg-black/40 px-2.5 py-1.5 font-mono text-[11px] text-amber-300 break-all select-all">
                {createdKey}
              </code>
              <button
                onClick={copyToClipboard}
                className="flex items-center gap-1 rounded border border-amber-500/30 bg-amber-500/20 px-3 py-1.5 text-xs font-medium text-amber-300 hover:bg-amber-500/30"
              >
                {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                {copied ? "Copied" : "Copy"}
              </button>
            </div>
          </div>
        )}

        {/* Keys Table */}
        <div className="overflow-hidden rounded-lg border border-border bg-muted/20">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-border bg-muted/40 text-muted-foreground">
              <tr>
                <th className="px-4 py-2.5 font-semibold">Name & Prefix</th>
                <th className="px-4 py-2.5 font-semibold">Rate Limit</th>
                <th className="px-4 py-2.5 font-semibold">Created</th>
                <th className="px-4 py-2.5 text-right font-semibold">Revoke</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {keys.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-6 text-center text-muted-foreground">
                    No active API keys created yet.
                  </td>
                </tr>
              ) : (
                keys.map((k) => (
                  <tr key={k.id} className="hover:bg-muted/30">
                    <td className="px-4 py-3">
                      <div className="font-semibold text-foreground">{k.name}</div>
                      <div className="font-mono text-[11px] text-muted-foreground">{k.key_prefix}...</div>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">{k.rate_limit_per_minute} req/min</td>
                    <td className="px-4 py-3 text-muted-foreground">{formatDate(k.created_at)}</td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => handleRevokeKey(k.id)}
                        title="Revoke Key"
                        className="rounded p-1.5 text-muted-foreground hover:bg-destructive/20 hover:text-destructive"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
