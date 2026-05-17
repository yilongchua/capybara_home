"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useCleanupPipelineRuns } from "@/core/control-plane/hooks";

import { SettingsSection } from "./settings-section";

export function PipelineCleanupSettingsPage() {
  const cleanupRuns = useCleanupPipelineRuns();
  const [days, setDays] = useState("14");

  return (
    <SettingsSection
      title="Pipeline Cleanup"
      description="Delete old scheduled pipeline runs to keep control-plane storage light."
    >
      <div className="rounded-lg border border-destructive/30 p-4 space-y-3">
        <div className="font-medium">Clear Old Scheduled Runs</div>
        <div className="text-sm text-muted-foreground">Only terminal scheduled runs are removed (completed/failed/cancelled/rejected).</div>
        <div className="flex items-center gap-2 max-w-md">
          <Input
            value={days}
            onChange={(e) => setDays(e.target.value)}
            placeholder="14"
            inputMode="numeric"
          />
          <Button
            variant="destructive"
            disabled={cleanupRuns.isPending}
            onClick={() => {
              const parsed = Number.parseInt(days, 10);
              const olderThanDays = Number.isFinite(parsed) && parsed > 0 ? parsed : 14;
              if (!window.confirm(`Delete scheduled runs older than ${olderThanDays} days?`)) return;
              cleanupRuns.mutate({ older_than_days: olderThanDays });
            }}
          >
            Delete Old Runs
          </Button>
        </div>
        {cleanupRuns.data ? (
          <div className="text-sm text-muted-foreground">Deleted {cleanupRuns.data.deleted} run(s).</div>
        ) : null}
      </div>
    </SettingsSection>
  );
}
