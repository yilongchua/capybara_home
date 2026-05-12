"use client";

import { CircleDotIcon, LoaderCircleIcon } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import {
  useIntegrationServicesStatus,
  useSetIntegrationServiceEnabled,
} from "@/core/control-plane";
import type {
  IntegrationServiceId,
  IntegrationServiceStatus,
} from "@/core/control-plane/types";
import { useI18n } from "@/core/i18n/hooks";

const orderedServiceIds: IntegrationServiceId[] = [
  "llm",
  "comfyui",
  "lightrag",
  "websearch",
];

function ServiceHealthLight({ healthy }: { healthy: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1 text-xs ${
        healthy ? "text-green-600" : "text-red-600"
      }`}
    >
      <CircleDotIcon className="size-3.5 fill-current" />
      {healthy ? "online" : "offline"}
    </span>
  );
}

function ServiceCard({
  service,
  toggling,
  onToggle,
}: {
  service: IntegrationServiceStatus;
  toggling: boolean;
  onToggle: (enabled: boolean) => void;
}) {
  const isEnabled = Boolean(
    service.phase === "starting" ||
      service.healthy ||
      service.docker_online,
  );
  const isManaged = Boolean(service.can_start || service.can_stop);

  return (
    <Card className="h-full">
      <CardHeader className="space-y-1">
        <div className="flex items-start justify-between gap-2">
          <CardTitle>{service.label}</CardTitle>
          <ServiceHealthLight healthy={service.healthy} />
        </div>
        <CardDescription>
          {service.error ? `Status: ${service.error}` : "Service health and startup controls."}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div className="rounded-md border p-3">
          <div className="grid grid-cols-[64px_1fr] gap-y-1">
            <span className="text-muted-foreground">Host</span>
            <span className="break-all">{service.host ?? "N/A"}</span>
            <span className="text-muted-foreground">Port</span>
            <span>{service.port ?? "N/A"}</span>
          </div>
        </div>
        <div className="flex items-center justify-between rounded-md border p-3">
          <div className="text-sm">
            <div className="font-medium">Enable service</div>
            <div className="text-muted-foreground text-xs">
              {isManaged
                ? isEnabled
                  ? "On: container/service should be active."
                  : "Off: service/container should be stopped."
                : "This integration is not managed by local-stack controls."}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {toggling && <LoaderCircleIcon className="size-4 animate-spin" />}
            <Switch
              checked={isEnabled}
              disabled={!isManaged || toggling}
              onCheckedChange={(checked) => onToggle(Boolean(checked))}
            />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export default function IntegrationsPage() {
  const { t } = useI18n();
  const { servicesStatus, isLoading } = useIntegrationServicesStatus();
  const toggleService = useSetIntegrationServiceEnabled();

  useEffect(() => {
    document.title = `${t.pages.integrations} - ${t.pages.appName}`;
  }, [t.pages.appName, t.pages.integrations]);

  const servicesById = new Map(
    (servicesStatus?.services ?? []).map((service) => [service.id, service]),
  );

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody>
        <div className="flex size-full flex-col overflow-y-auto">
          <div className="border-b px-6 py-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h1 className="text-xl font-semibold">Integrations Overview</h1>
                <p className="text-muted-foreground mt-0.5 text-sm">
                  Check local integrations before starting a new chat.
                </p>
              </div>
              <Button asChild size="lg">
                <Link href="/workspace/chats/new">Proceed</Link>
              </Button>
            </div>
          </div>

          <div className="p-6">
            {isLoading ? (
              <div className="text-muted-foreground flex items-center gap-2 text-sm">
                <LoaderCircleIcon className="size-4 animate-spin" />
                Loading integration status...
              </div>
            ) : (
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {orderedServiceIds.map((serviceId) => {
                  const service = servicesById.get(serviceId);
                  if (!service) {
                    return (
                      <Card key={serviceId} className="h-full">
                        <CardHeader>
                          <CardTitle>{serviceId}</CardTitle>
                          <CardDescription>Service status unavailable.</CardDescription>
                        </CardHeader>
                      </Card>
                    );
                  }
                  return (
                    <ServiceCard
                      key={service.id}
                      service={service}
                      toggling={
                        toggleService.isPending &&
                        toggleService.variables?.serviceId === service.id
                      }
                      onToggle={(enabled) =>
                        toggleService.mutate(
                          { serviceId: service.id, enabled },
                          {
                            onSuccess: (result) => {
                              toast.success(result.message);
                            },
                            onError: (error) => toast.error(error.message),
                          },
                        )
                      }
                    />
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
