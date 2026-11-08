"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { LogOut, User, ShieldCheck } from "lucide-react";
import { getStoredUser, logout, UserProfile } from "@/lib/auth";

export function Topbar() {
  const router = useRouter();
  const [user, setUser] = useState<UserProfile | null>(null);

  useEffect(() => {
    setUser(getStoredUser());
  }, []);

  const handleSignOut = async () => {
    await logout();
    router.replace("/login");
  };

  const primaryRole = user?.roles?.[0]?.name || "Standard User";

  return (
    <header className="sticky top-0 z-30 flex h-16 w-full items-center justify-between border-b border-border bg-card/40 px-8 backdrop-blur-md">
      <div className="flex items-center gap-3">
        <span className="text-xs uppercase tracking-wider text-muted-foreground font-semibold">Environment</span>
        <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-0.5 text-xs font-medium text-emerald-400">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
          Development (API Ready)
        </span>
      </div>

      <div className="flex items-center gap-4">
        {user ? (
          <div className="flex items-center gap-3">
            <div className="flex flex-col text-right">
              <span className="text-xs font-semibold leading-tight">{user.email}</span>
              <div className="flex items-center justify-end gap-1 text-[11px] text-muted-foreground capitalize">
                <ShieldCheck className="h-3 w-3 text-primary" />
                {primaryRole.replace("_", " ")}
              </div>
            </div>
            <button
              onClick={handleSignOut}
              title="Sign Out"
              className="flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-muted/30 text-muted-foreground transition-colors hover:bg-destructive/20 hover:text-destructive"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        ) : (
          <button
            onClick={() => router.push("/login")}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
          >
            <User className="h-3.5 w-3.5" />
            Sign In
          </button>
        )}
      </div>
    </header>
  );
}
