"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function HomePage() {
  const router = useRouter();

  useEffect(() => {
    // middleware.ts sends visitors without a session to /login before this renders.
    router.replace("/overview");
  }, [router]);

  return (
    <div className="flex h-screen w-full items-center justify-center bg-background text-muted-foreground">
      <div className="flex flex-col items-center gap-3">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <span className="text-sm font-medium tracking-wide">Initializing RADAR...</span>
      </div>
    </div>
  );
}
