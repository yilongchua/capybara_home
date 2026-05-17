"use client";

import { Button } from "@/components/ui/button";
import { useCleanupAutoresearch } from "@/core/control-plane/hooks";

import { SettingsSection } from "./settings-section";

export function AutoresearchCleanupSettingsPage() {
  const cleanup = useCleanupAutoresearch();

  return (
    <SettingsSection
      title="Autoresearch Cleanup"
      description="Clear autoresearch objectives and optional related runs/artifacts to keep the system clean."
    >
      <div className="rounded-lg border border-destructive/30 p-4 space-y-3">
        <div className="font-medium">Delete All Autoresearch Data</div>
        <div className="text-sm text-muted-foreground">This removes all objectives, schedules, and their vault-tracking files.</div>
        <div className="flex gap-2">
          <Button
            variant="destructive"
            disabled={cleanup.isPending}
            onClick={() => {
              if (!window.confirm("Delete all autoresearch objectives and related runs?")) return;
              cleanup.mutate(true);
            }}
          >
            Delete Objectives + Runs
          </Button>
          <Button
            variant="outline"
            disabled={cleanup.isPending}
            onClick={() => {
              if (!window.confirm("Delete all autoresearch objectives but keep runs?")) return;
              cleanup.mutate(false);
            }}
          >
            Delete Objectives Only
          </Button>
        </div>
        {cleanup.data ? (
          <div className="text-sm text-muted-foreground">
            Deleted {cleanup.data.deleted_objectives} objective(s).
          </div>
        ) : null}
      </div>
    </SettingsSection>
  );
}
