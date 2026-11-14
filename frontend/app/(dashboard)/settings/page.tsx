"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  CircleDashed,
  Copy,
  Key,
  Laptop,
  Loader2,
  LockKeyhole,
  Plug,
  Plus,
  Search,
  ShieldCheck,
  Trash2,
  User,
  Users,
} from "lucide-react";
import { fetchApi } from "@/lib/api-client";
import { setStoredUser, type UserProfile } from "@/lib/auth";
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

interface SessionItem {
  id: string;
  ip_address: string | null;
  user_agent: string | null;
  signed_in_at: string;
  last_active_at: string;
  current: boolean;
}

interface Integration {
  key: string;
  name: string;
  kind: "SOURCE" | "AI" | "MONITORING";
  configured: boolean;
  credentials: { name: string; configured: boolean }[];
  note: string | null;
}

interface AdminUser {
  id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  roles: { id: string; name: string }[];
  created_at: string;
  last_login_at: string | null;
}

const ROLES = [
  { value: "standard_user", label: "Standard user" },
  { value: "researcher", label: "Researcher" },
  { value: "admin", label: "Admin" },
  { value: "super_admin", label: "Super admin" },
];
const roleLabel = (name: string) => ROLES.find((r) => r.value === name)?.label ?? name.replace(/_/g, " ");

const inputClass =
  "w-full rounded-lg border border-input bg-muted/40 px-3 py-2 text-xs text-foreground placeholder-muted-foreground focus:border-primary focus:outline-none";
const primaryButton =
  "inline-flex items-center justify-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-xs font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50";
const quietButton =
  "inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-xs font-medium text-foreground hover:bg-muted disabled:opacity-50";

/** "Chrome on Windows" from a user-agent string; good enough to recognise your own devices. */
function describeDevice(ua: string | null): string {
  if (!ua) return "Unknown device";
  if (/python|httpx|curl|postman|okhttp/i.test(ua)) return "API client";
  const browser = /Edg\//.test(ua) ? "Edge"
    : /OPR\/|Opera/.test(ua) ? "Opera"
    : /Firefox\//.test(ua) ? "Firefox"
    : /Chrome\//.test(ua) ? "Chrome"
    : /Safari\//.test(ua) ? "Safari"
    : "Browser";
  const os = /Windows/.test(ua) ? "Windows"
    : /Android/.test(ua) ? "Android"
    : /iPhone|iPad|iOS/.test(ua) ? "iOS"
    : /Mac OS X|Macintosh/.test(ua) ? "macOS"
    : /Linux/.test(ua) ? "Linux"
    : "unknown OS";
  return `${browser} on ${os}`;
}

function Section({ icon: Icon, title, description, children, id }: {
  icon: typeof User;
  title: string;
  description?: string;
  children: React.ReactNode;
  id: string;
}) {
  return (
    <section id={id} className="scroll-mt-20 rounded-xl border border-border bg-card/60 p-6 shadow-sm backdrop-blur-md">
      <h2 className="flex items-center gap-2 text-base font-semibold">
        <Icon className="h-4 w-4 text-primary" />
        {title}
      </h2>
      {description && <p className="mt-1 text-xs text-muted-foreground">{description}</p>}
      <div className="mt-5">{children}</div>
    </section>
  );
}

function Notice({ kind, children }: { kind: "ok" | "error"; children: React.ReactNode }) {
  return (
    <p
      role={kind === "error" ? "alert" : "status"}
      className={`flex items-center gap-1.5 text-xs ${kind === "ok" ? "text-emerald-400" : "text-red-400"}`}
    >
      {kind === "ok" ? <CheckCircle2 className="h-3.5 w-3.5" /> : <AlertTriangle className="h-3.5 w-3.5" />}
      {children}
    </p>
  );
}

// --- Profile -----------------------------------------------------------------

function ProfileSection({ user, onUpdated }: { user: UserProfile; onUpdated: (u: UserProfile) => void }) {
  const [name, setName] = useState(user.full_name ?? "");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    const res = await fetchApi<UserProfile>("/auth/me", { method: "PATCH", body: JSON.stringify({ full_name: name }) });
    setSaving(false);
    if (res.data) {
      onUpdated(res.data);
      setNotice({ kind: "ok", text: "Saved." });
    } else setNotice({ kind: "error", text: res.error ?? "Could not save." });
  };

  return (
    <Section id="profile" icon={User} title="Profile">
      <div className="grid gap-5 sm:grid-cols-2">
        <form onSubmit={save} className="space-y-2">
          <label htmlFor="full-name" className="text-xs text-muted-foreground">Display name</label>
          <div className="flex gap-2">
            <input id="full-name" value={name} maxLength={160} onChange={(e) => setName(e.target.value)}
                   placeholder="Your name" className={inputClass} />
            <button type="submit" disabled={saving || name === (user.full_name ?? "")} className={primaryButton}>
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Save"}
            </button>
          </div>
          {notice && <Notice kind={notice.kind}>{notice.text}</Notice>}
        </form>
        <div className="space-y-3 text-xs">
          <div>
            <span className="text-muted-foreground">Email</span>
            <div className="mt-0.5 font-semibold">{user.email}</div>
          </div>
          <div>
            <span className="text-muted-foreground">Role</span>
            <div className="mt-0.5 flex items-center gap-1.5 font-semibold">
              <ShieldCheck className="h-3.5 w-3.5 text-primary" />
              {user.roles.map((r) => roleLabel(r.name)).join(", ") || "Standard user"}
            </div>
          </div>
        </div>
      </div>
    </Section>
  );
}

// --- Password ----------------------------------------------------------------

function PasswordSection({ onChanged }: { onChanged: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const mismatch = confirm.length > 0 && next !== confirm;
  const tooShort = next.length > 0 && next.length < 8;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (mismatch || tooShort) return;
    setSaving(true);
    const res = await fetchApi("/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password: current, new_password: next }),
    });
    setSaving(false);
    if (res.status === 204) {
      setCurrent("");
      setNext("");
      setConfirm("");
      setNotice({ kind: "ok", text: "Password changed. Your other devices have been signed out." });
      onChanged();
    } else setNotice({ kind: "error", text: res.error ?? "Could not change the password." });
  };

  return (
    <Section id="password" icon={LockKeyhole} title="Password"
             description="Changing your password signs out every other device. This browser stays signed in.">
      <form onSubmit={submit} className="grid max-w-md gap-3">
        <input type="password" autoComplete="current-password" required value={current}
               onChange={(e) => setCurrent(e.target.value)} placeholder="Current password" className={inputClass}
               aria-label="Current password" />
        <input type="password" autoComplete="new-password" required minLength={8} maxLength={128} value={next}
               onChange={(e) => setNext(e.target.value)} placeholder="New password (at least 8 characters)"
               className={inputClass} aria-label="New password" />
        <input type="password" autoComplete="new-password" required value={confirm}
               onChange={(e) => setConfirm(e.target.value)} placeholder="Confirm new password" className={inputClass}
               aria-label="Confirm new password" />
        {tooShort && <Notice kind="error">Use at least 8 characters.</Notice>}
        {mismatch && <Notice kind="error">The new passwords don&apos;t match.</Notice>}
        {notice && <Notice kind={notice.kind}>{notice.text}</Notice>}
        <div>
          <button type="submit" disabled={saving || mismatch || tooShort || !current || !next || !confirm}
                  className={primaryButton}>
            {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            Change password
          </button>
        </div>
      </form>
    </Section>
  );
}

// --- Sessions ----------------------------------------------------------------

function SessionsSection({ refreshKey }: { refreshKey: number }) {
  const [sessions, setSessions] = useState<SessionItem[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const load = useCallback(async () => {
    const res = await fetchApi<SessionItem[]>("/auth/sessions");
    setSessions(res.data ?? []);
  }, []);
  useEffect(() => {
    load();
  }, [load, refreshKey]);

  const revoke = async (id: string) => {
    setBusy(id);
    const res = await fetchApi(`/auth/sessions/${id}`, { method: "DELETE" });
    setBusy(null);
    if (res.status === 204) await load();
    else setNotice({ kind: "error", text: res.error ?? "Could not sign out that device." });
  };

  const signOutOthers = async () => {
    setBusy("others");
    const res = await fetchApi<{ sessions_ended: number }>("/auth/logout-others", { method: "POST" });
    setBusy(null);
    if (res.data) {
      const n = res.data.sessions_ended;
      setNotice({ kind: "ok", text: n ? `Signed out ${n} other device${n === 1 ? "" : "s"}.` : "No other devices were signed in." });
      await load();
    } else setNotice({ kind: "error", text: res.error ?? "Could not sign out other devices." });
  };

  const others = sessions?.filter((s) => !s.current).length ?? 0;

  return (
    <Section id="sessions" icon={Laptop} title="Signed-in devices"
             description="Devices that can use your account. Sign out any you don't recognise.">
      {sessions === null ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading…</div>
      ) : (
        <div className="space-y-3">
          <ul className="divide-y divide-border/60 rounded-lg border border-border bg-muted/20">
            {sessions.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-xs">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 font-semibold">
                    {describeDevice(s.user_agent)}
                    {s.current && (
                      <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-400">
                        This browser
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 text-[11px] text-muted-foreground">
                    {s.ip_address ?? "Unknown IP"} · signed in {formatDate(s.signed_in_at)} · last active {formatDate(s.last_active_at)}
                  </div>
                </div>
                {!s.current && (
                  <button type="button" onClick={() => revoke(s.id)} disabled={busy !== null} className={quietButton}>
                    {busy === s.id && <Loader2 className="h-3 w-3 animate-spin" />}
                    Sign out
                  </button>
                )}
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap items-center gap-3">
            <button type="button" onClick={signOutOthers} disabled={busy !== null || others === 0} className={quietButton}>
              {busy === "others" && <Loader2 className="h-3 w-3 animate-spin" />}
              Sign out all other devices
            </button>
            {notice && <Notice kind={notice.kind}>{notice.text}</Notice>}
          </div>
        </div>
      )}
    </Section>
  );
}

// --- API keys ----------------------------------------------------------------

function ApiKeysSection() {
  const [keys, setKeys] = useState<ApiKeyItem[]>([]);
  const [newKeyName, setNewKeyName] = useState("");
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [loading, setLoading] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadKeys = useCallback(async () => {
    const res = await fetchApi<ApiKeyItem[]>("/auth/api-keys");
    if (res.data) setKeys(res.data);
  }, []);
  useEffect(() => {
    loadKeys();
  }, [loadKeys]);

  const handleCreateKey = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newKeyName.trim()) return;
    setLoading(true);
    setError(null);
    const res = await fetchApi<{ raw_api_key: string }>("/auth/api-keys", {
      method: "POST",
      body: JSON.stringify({ name: newKeyName.trim(), scopes: ["read", "write"], rate_limit_per_minute: 60 }),
    });
    setLoading(false);
    if (res.data) {
      setCreatedKey(res.data.raw_api_key);
      setNewKeyName("");
      loadKeys();
    } else setError(res.error ?? "Could not create the key.");
  };

  const revoke = async (id: string) => {
    await fetchApi(`/auth/api-keys/${id}`, { method: "DELETE" });
    setConfirming(null);
    loadKeys();
  };

  const copyToClipboard = async () => {
    if (!createdKey) return;
    try {
      await navigator.clipboard.writeText(createdKey);
      setCopied(true);
      setTimeout(() => setCopied(false), 3000);
    } catch {
      setError("Copy failed: select the key and copy it manually.");
    }
  };

  return (
    <Section id="api-keys" icon={Key} title="API keys"
             description="For scripts and other apps that call RADAR. Send the key in an X-API-Key header.">
      <div className="space-y-5">
        <form onSubmit={handleCreateKey} className="flex flex-col gap-3 sm:flex-row">
          <input type="text" required maxLength={100} value={newKeyName} onChange={(e) => setNewKeyName(e.target.value)}
                 placeholder="What is this key for? e.g. Weekly export script" className={inputClass} aria-label="Key name" />
          <button type="submit" disabled={loading} className={primaryButton}>
            <Plus className="h-3.5 w-3.5" />
            Create key
          </button>
        </form>
        {error && <Notice kind="error">{error}</Notice>}

        {createdKey && (
          <div className="space-y-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-xs">
            <div className="font-semibold text-amber-400">Copy your key now</div>
            <p className="text-[11px] text-muted-foreground">It won&apos;t be shown again. Store it somewhere safe, like a password manager.</p>
            <div className="flex items-center gap-2">
              <code className="flex-1 select-all break-all rounded bg-black/40 px-2.5 py-1.5 font-mono text-[11px] text-amber-300">
                {createdKey}
              </code>
              <button type="button" onClick={copyToClipboard}
                      className="flex items-center gap-1 rounded border border-amber-500/30 bg-amber-500/20 px-3 py-1.5 text-xs font-medium text-amber-300 hover:bg-amber-500/30">
                {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                {copied ? "Copied" : "Copy"}
              </button>
            </div>
            <button type="button" onClick={() => setCreatedKey(null)} className="text-[11px] text-muted-foreground hover:text-foreground">
              I&apos;ve saved it
            </button>
          </div>
        )}

        <div className="overflow-x-auto rounded-lg border border-border bg-muted/20">
          <table className="w-full min-w-[520px] text-left text-xs">
            <thead className="border-b border-border bg-muted/40 text-muted-foreground">
              <tr>
                <th className="px-4 py-2.5 font-semibold">Name</th>
                <th className="px-4 py-2.5 font-semibold">Created</th>
                <th className="px-4 py-2.5 font-semibold">Last used</th>
                <th className="px-4 py-2.5 text-right font-semibold"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {keys.length === 0 ? (
                <tr><td colSpan={4} className="px-4 py-6 text-center text-muted-foreground">No API keys yet.</td></tr>
              ) : (
                keys.map((k) => (
                  <tr key={k.id}>
                    <td className="px-4 py-3">
                      <div className="font-semibold">{k.name}</div>
                      <div className="font-mono text-[11px] text-muted-foreground">{k.key_prefix}… · {k.rate_limit_per_minute} req/min</div>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">{formatDate(k.created_at)}</td>
                    <td className="px-4 py-3 text-muted-foreground">{k.last_used_at ? formatDate(k.last_used_at) : "Never"}</td>
                    <td className="px-4 py-3 text-right">
                      {confirming === k.id ? (
                        <span className="inline-flex items-center gap-2">
                          <span className="text-muted-foreground">Revoke?</span>
                          <button type="button" onClick={() => revoke(k.id)}
                                  className="rounded bg-destructive px-2 py-1 font-semibold text-destructive-foreground">Revoke</button>
                          <button type="button" onClick={() => setConfirming(null)} className="text-muted-foreground hover:text-foreground">Cancel</button>
                        </span>
                      ) : (
                        <button type="button" onClick={() => setConfirming(k.id)} title="Revoke key" aria-label={`Revoke ${k.name}`}
                                className="rounded p-1.5 text-muted-foreground hover:bg-destructive/20 hover:text-destructive">
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </Section>
  );
}

// --- Integrations ------------------------------------------------------------

function IntegrationsSection() {
  const [items, setItems] = useState<Integration[] | null>(null);
  useEffect(() => {
    fetchApi<Integration[]>("/admin/integrations").then((r) => setItems(r.data ?? []));
  }, []);

  return (
    <Section id="integrations" icon={Plug} title="Integrations"
             description="External keys RADAR uses. Only whether each key is set is shown, never the key itself.">
      {items === null ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading…</div>
      ) : (
        <ul className="divide-y divide-border/60 rounded-lg border border-border bg-muted/20">
          {items.map((i) => (
            <li key={i.key} className="flex flex-wrap items-start justify-between gap-3 px-4 py-3 text-xs">
              <div className="min-w-0">
                <div className="font-semibold">{i.name}</div>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {i.credentials.map((c) => (
                    <code key={c.name}
                          className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${c.configured ? "bg-emerald-500/10 text-emerald-400" : "bg-muted text-muted-foreground"}`}>
                      {c.name} {c.configured ? "✓" : "missing"}
                    </code>
                  ))}
                </div>
                {i.note && <p className="mt-1 text-[11px] text-muted-foreground">{i.note}</p>}
              </div>
              <span className={`inline-flex shrink-0 items-center gap-1 font-medium ${i.configured ? "text-emerald-400" : "text-muted-foreground"}`}>
                {i.configured ? <CheckCircle2 className="h-3.5 w-3.5" /> : <CircleDashed className="h-3.5 w-3.5" />}
                {i.configured ? "Connected" : i.kind === "SOURCE" ? "Needs a key" : "Off"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

// --- Users (admins only) ---------------------------------------------------

function UsersSection({ me }: { me: UserProfile }) {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const isSuper = me.roles.some((r) => r.name === "super_admin");

  const load = useCallback(async (term = "") => {
    const res = await fetchApi<AdminUser[]>(`/admin/users${term ? `?search=${encodeURIComponent(term)}` : ""}`);
    setUsers(res.data ?? []);
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  const update = async (u: AdminUser, change: { role?: string; is_active?: boolean }) => {
    setBusy(u.id);
    setNotice(null);
    const res = await fetchApi<AdminUser>(`/admin/users/${u.id}`, { method: "PATCH", body: JSON.stringify(change) });
    setBusy(null);
    if (res.data) {
      const updated = res.data;
      setUsers((list) => list?.map((x) => (x.id === u.id ? updated : x)) ?? null);
      setNotice({ kind: "ok", text: `Updated ${u.email}.` });
    } else setNotice({ kind: "error", text: res.error ?? "Could not update the user." });
  };

  return (
    <Section id="users" icon={Users} title="Users"
             description={isSuper
               ? "Change roles or deactivate accounts. Deactivating signs the person out everywhere."
               : "Change roles for researchers and standard users. Only a super admin can manage administrators."}>
      <form onSubmit={(e) => { e.preventDefault(); load(search.trim()); }} className="relative mb-4 max-w-sm">
        <Search className="absolute left-3 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
        <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search by email or name"
               className={`${inputClass} pl-8`} aria-label="Search users" />
      </form>
      {notice && <div className="mb-3"><Notice kind={notice.kind}>{notice.text}</Notice></div>}
      {users === null ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading…</div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-muted/20">
          <table className="w-full min-w-[640px] text-left text-xs">
            <thead className="border-b border-border bg-muted/40 text-muted-foreground">
              <tr>
                <th className="px-4 py-2.5 font-semibold">User</th>
                <th className="px-4 py-2.5 font-semibold">Role</th>
                <th className="px-4 py-2.5 font-semibold">Last sign-in</th>
                <th className="px-4 py-2.5 text-right font-semibold">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {users.map((u) => {
                const role = u.roles[0]?.name ?? "standard_user";
                const self = u.id === me.id;
                const privileged = role === "admin" || role === "super_admin";
                const locked = self || (!isSuper && privileged);
                return (
                  <tr key={u.id} className={u.is_active ? "" : "opacity-60"}>
                    <td className="px-4 py-3">
                      <div className="font-semibold">{u.full_name || u.email}{self && <span className="ml-1.5 text-muted-foreground">(you)</span>}</div>
                      {u.full_name && <div className="text-[11px] text-muted-foreground">{u.email}</div>}
                    </td>
                    <td className="px-4 py-3">
                      <select value={role} disabled={locked || busy === u.id}
                              onChange={(e) => update(u, { role: e.target.value })}
                              aria-label={`Role for ${u.email}`}
                              className="rounded-md border border-input bg-card px-2 py-1 text-xs disabled:opacity-60">
                        {ROLES.filter((r) => isSuper || !["admin", "super_admin"].includes(r.value) || r.value === role).map((r) => (
                          <option key={r.value} value={r.value}>{r.label}</option>
                        ))}
                      </select>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">{u.last_login_at ? formatDate(u.last_login_at) : "Never"}</td>
                    <td className="px-4 py-3 text-right">
                      <button type="button" disabled={locked || busy === u.id}
                              onClick={() => update(u, { is_active: !u.is_active })}
                              className={`${quietButton} ${u.is_active ? "" : "border-emerald-500/40 text-emerald-400"}`}>
                        {busy === u.id && <Loader2 className="h-3 w-3 animate-spin" />}
                        {u.is_active ? "Deactivate" : "Reactivate"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}

// --- Page --------------------------------------------------------------------

export default function SettingsPage() {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sessionsVersion, setSessionsVersion] = useState(0);

  useEffect(() => {
    fetchApi<UserProfile>("/auth/me").then((r) => {
      if (r.data) {
        setUser(r.data);
        setStoredUser(r.data);
      } else setError(r.error ?? "Could not load your account.");
    });
  }, []);

  const onProfileUpdated = (u: UserProfile) => {
    setUser(u);
    setStoredUser(u);
  };

  const isAdmin = !!user?.roles.some((r) => r.name === "admin" || r.name === "super_admin");
  const nav = [
    ["profile", "Profile"], ["password", "Password"], ["sessions", "Devices"], ["api-keys", "API keys"],
    ["integrations", "Integrations"], ...(isAdmin ? [["users", "Users"]] : []),
  ];

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground">Your account, security and integrations.</p>
      </div>

      {error && <Notice kind="error">{error}</Notice>}
      {!user && !error && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</div>
      )}

      {user && (
        <>
          <nav aria-label="Settings sections" className="flex flex-wrap gap-2">
            {nav.map(([id, label]) => (
              <a key={id} href={`#${id}`}
                 className="rounded-lg border border-border bg-card/50 px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground">
                {label}
              </a>
            ))}
          </nav>
          <ProfileSection user={user} onUpdated={onProfileUpdated} />
          <PasswordSection onChanged={() => setSessionsVersion((v) => v + 1)} />
          <SessionsSection refreshKey={sessionsVersion} />
          <ApiKeysSection />
          <IntegrationsSection />
          {isAdmin && <UsersSection me={user} />}
        </>
      )}
    </div>
  );
}
