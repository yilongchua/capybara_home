"use client";

import { CalendarClockIcon } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";

export default function PipelinesPage() {
  const { t } = useI18n();

  useEffect(() => {
    document.title = `${t.pages.pipelines} - ${t.pages.appName}`;
  }, [t.pages.appName, t.pages.pipelines]);

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody>
        <div className="flex size-full flex-col overflow-y-auto">
          <div className="border-b px-6 py-4">
            <h1 className="flex items-center gap-2 text-xl font-semibold">
              <CalendarClockIcon className="size-5" />
              {t.pages.pipelines}
            </h1>
            <p className="text-muted-foreground mt-0.5 text-sm">
              Scheduled pipeline controls now live in each objective card in Knowledge Vault.
            </p>
          </div>

          <div className="p-6">
            <Card>
              <CardHeader>
                <CardTitle>Manage in Knowledge Vault</CardTitle>
                <CardDescription>
                  Use the Knowledge Vault objective cards to run schedules, update daily time, edit endpoint goal, and delete a schedule.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Button asChild>
                  <Link href="/workspace/vault">Open Knowledge Vault</Link>
                </Button>
              </CardContent>
            </Card>
          </div>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
