"use client";

import { BrainCircuit, Cpu, DollarSign, Activity } from "lucide-react";

export default function IntelligencePage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">AI Intelligence Engine</h1>
        <p className="text-sm text-muted-foreground">Provider-independent LLM telemetry, cost tracking, and entity classification.</p>
      </div>

      <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
        <div className="rounded-xl border border-border bg-card/60 p-5 backdrop-blur-md">
          <div className="flex items-center justify-between text-muted-foreground text-xs">
            <span>Primary Provider</span>
            <Cpu className="h-4 w-4 text-primary" />
          </div>
          <div className="mt-2 text-lg font-bold">Google Gemini / OpenAI / Local</div>
          <p className="text-[11px] text-muted-foreground mt-1">Configurable via GEMINI_API_KEY / OPENAI_API_KEY</p>
        </div>

        <div className="rounded-xl border border-border bg-card/60 p-5 backdrop-blur-md">
          <div className="flex items-center justify-between text-muted-foreground text-xs">
            <span>AI Status</span>
            <Activity className="h-4 w-4 text-emerald-400" />
          </div>
          <div className="mt-2 text-lg font-bold">Optional Execution</div>
          <p className="text-[11px] text-muted-foreground mt-1">Basic scraping operates 100% with AI_ENABLED=false</p>
        </div>

        <div className="rounded-xl border border-border bg-card/60 p-5 backdrop-blur-md">
          <div className="flex items-center justify-between text-muted-foreground text-xs">
            <span>Token & Cost Log</span>
            <DollarSign className="h-4 w-4 text-amber-400" />
          </div>
          <div className="mt-2 text-lg font-bold">$0.00 USD</div>
          <p className="text-[11px] text-muted-foreground mt-1">Compact pre-extracted snippets only</p>
        </div>
      </div>

      <div className="rounded-xl border border-dashed border-border bg-card/40 p-12 text-center backdrop-blur-md">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-purple-500/10 text-purple-400">
          <BrainCircuit className="h-6 w-6" />
        </div>
        <h3 className="mt-4 text-base font-semibold">Structured AI Pipeline (Phase 6)</h3>
        <p className="mx-auto mt-2 max-w-md text-xs text-muted-foreground">
          Pydantic JSON schema extraction, skills taxonomy mapping, deadline detection, and semantic duplicate tie-breaking will be wired in Phase 6.
        </p>
      </div>
    </div>
  );
}
