"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Radar, ArrowRight, ShieldCheck, AlertCircle } from "lucide-react";
import { fetchApi } from "@/lib/api-client";
import { setStoredUser } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const loginRes = await fetchApi("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });

      if (loginRes.error || !loginRes.data) {
        setError(loginRes.error || "Login failed. Check your credentials.");
        setLoading(false);
        return;
      }

      // The API set httpOnly session cookies; fetch the profile for display.
      const meRes = await fetchApi("/auth/me");
      if (meRes.data) {
        setStoredUser(meRes.data);
      }

      router.push("/overview");
    } catch (err: any) {
      setError(err.message || "An unexpected error occurred.");
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4 py-12">
      <div className="w-full max-w-md space-y-8 rounded-xl border border-border bg-card/80 p-8 shadow-2xl backdrop-blur-md">
        <div className="flex flex-col items-center text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-lg shadow-primary/20">
            <Radar className="h-6 w-6" />
          </div>
          <h2 className="mt-4 text-2xl font-bold tracking-tight">Sign in to RADAR</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Unified Web Intelligence & Discovery Platform
          </p>
        </div>

        {error && (
          <div className="flex items-center gap-2 rounded-lg border border-destructive/50 bg-destructive/10 p-3 text-xs text-red-400">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-muted-foreground">Work Email</label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="operator@organization.com"
              className="mt-1 block w-full rounded-lg border border-input bg-muted/40 px-3 py-2 text-sm text-foreground placeholder-muted-foreground focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-muted-foreground">Password</label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••••••"
              className="mt-1 block w-full rounded-lg border border-input bg-muted/40 px-3 py-2 text-sm text-foreground placeholder-muted-foreground focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-primary py-2.5 text-sm font-semibold text-primary-foreground shadow transition hover:bg-primary/90 disabled:opacity-50"
          >
            {loading ? "Authenticating..." : "Sign In to Console"}
            <ArrowRight className="h-4 w-4" />
          </button>
        </form>

        <div className="border-t border-border pt-4 text-center text-xs text-muted-foreground">
          Don&apos;t have an account yet?{" "}
          <Link href="/register" className="font-medium text-primary hover:underline">
            Register new operator
          </Link>
        </div>
      </div>
    </div>
  );
}
