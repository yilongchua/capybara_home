"use client";

import { LoaderCircleIcon, PlayIcon } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getBackendBaseURL } from "@/core/config";
import type {
  IntegrationServiceStartResponse,
  IntegrationServiceStatus,
  IntegrationServicesStatusResponse,
  StartupJob,
} from "@/core/control-plane/types";

const serviceOrder: Array<IntegrationServiceStatus["id"]> = [
  "llm",
  "comfyui",
  "lightrag",
  "websearch",
];

export default function HomePage() {
  const [services, setServices] = useState<IntegrationServiceStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [startingId, setStartingId] = useState<string | null>(null);
  const [startingAll, setStartingAll] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [dockerDesktopOnline, setDockerDesktopOnline] = useState<boolean | null>(
    null,
  );
  const [dockerDesktopError, setDockerDesktopError] = useState<string | null>(null);
  const [dockerServices, setDockerServices] = useState<
    Array<{ name: string; status: string; online: boolean }>
  >([]);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [startupJob, setStartupJob] = useState<StartupJob | null>(null);

  const sortedServices = useMemo(() => {
    const rank = new Map(serviceOrder.map((id, index) => [id, index]));
    return [...services].sort((a, b) => {
      const ai = rank.get(a.id) ?? 99;
      const bi = rank.get(b.id) ?? 99;
      return ai - bi;
    });
  }, [services]);

  const loadServices = async (showLoader = true) => {
    if (showLoader) {
      setLoading(true);
    }
    try {
      const response = await fetch(`${getBackendBaseURL()}/api/integrations/services`);
      if (!response.ok) {
        throw new Error(`Failed to load integrations (${response.status}).`);
      }
      const payload = (await response.json()) as IntegrationServicesStatusResponse;
      setServices(payload.services);
      setDockerDesktopOnline(payload.docker_desktop_online ?? null);
      setDockerDesktopError(payload.docker_desktop_error ?? null);
      setDockerServices(payload.docker_services ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load integrations.");
    } finally {
      if (showLoader) {
        setLoading(false);
      }
    }
  };

  const startService = async (serviceId: string) => {
    setStartingId(serviceId);
    setMessage(null);
    setError(null);
    try {
      const response = await fetch(
        `${getBackendBaseURL()}/api/integrations/services/${serviceId}/start`,
        { method: "POST" },
      );
      const payload = (await response.json().catch(() => ({}))) as Partial<IntegrationServiceStartResponse> & {
        detail?: string;
      };
      if (!response.ok) {
        throw new Error(payload.detail ?? `Failed to start ${serviceId}.`);
      }
      if (!payload.job_id) {
        throw new Error("Startup job ID missing from backend response.");
      }
      setActiveJobId(payload.job_id);
      setMessage(payload.message ?? `${serviceId} startup job queued.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : `Failed to start ${serviceId}.`);
    } finally {
      setStartingId(null);
    }
  };

  const startAllServices = async () => {
    setStartingAll(true);
    setMessage(null);
    setError(null);
    try {
      const response = await fetch(
        `${getBackendBaseURL()}/api/integrations/services/start-all`,
        { method: "POST" },
      );
      const payload = (await response.json().catch(() => ({}))) as Partial<IntegrationServiceStartResponse> & {
        detail?: string;
      };
      if (!response.ok) {
        throw new Error(payload.detail ?? "Failed to start all services.");
      }
      if (!payload.job_id) {
        throw new Error("Startup job ID missing from backend response.");
      }
      setActiveJobId(payload.job_id);
      setMessage(payload.message ?? "Startup job queued for all integrations.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start all services.");
    } finally {
      setStartingAll(false);
    }
  };

  useEffect(() => {
    if (!activeJobId) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const response = await fetch(
          `${getBackendBaseURL()}/api/integrations/startup-jobs/${activeJobId}`,
        );
        if (!response.ok) return;
        const job = (await response.json()) as StartupJob;
        if (cancelled) return;
        setStartupJob(job);
        await loadServices(false);
        if (job.status === "success") {
          setMessage("Startup validation completed successfully.");
          setActiveJobId(null);
          return;
        }
        if (job.status === "failed") {
          setError(job.error ?? "Startup job failed.");
          setActiveJobId(null);
          return;
        }
        setTimeout(() => {
          void poll();
        }, 2000);
      } catch {
        if (!cancelled) {
          setTimeout(() => {
            void poll();
          }, 3000);
        }
      }
    };
    void poll();
    return () => {
      cancelled = true;
    };
  }, [activeJobId]);

  useEffect(() => {
    void loadServices();
  }, []);

  useEffect(() => {
    if (activeJobId) return;
    const timer = window.setInterval(() => {
      void loadServices(false);
    }, 5000);
    return () => {
      window.clearInterval(timer);
    };
  }, [activeJobId]);

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-5xl flex-col gap-6 px-4 py-6 md:px-6">
      <Image
        src="/banner.png"
        alt="Capybara Home Banner"
        width={1400}
        height={320}
        className="h-44 w-full rounded-lg object-cover md:h-56"
        priority
      />
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-3">
          <div>
            <CardTitle>Welcome to Capybara Home: New Chat</CardTitle>
            <p className="text-muted-foreground mt-1 text-sm">
              Docker Desktop and integrations status before starting chat.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              disabled={startingAll || activeJobId !== null}
              onClick={() => void startAllServices()}
            >
              {startingAll ? (
                <>
                  <LoaderCircleIcon className="mr-1.5 size-4 animate-spin" />
                  Starting all...
                </>
              ) : (
                "Start up all docker compose"
              )}
            </Button>
            <Button asChild>
              <Link href="/workspace/chats/new">New chat</Link>
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-muted-foreground">Docker Desktop:</span>
            <span
              className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs ${
                dockerDesktopOnline === true
                  ? "bg-green-100 text-green-700"
                  : dockerDesktopOnline === false
                    ? "bg-red-100 text-red-700"
                    : "bg-gray-100 text-gray-700"
              }`}
            >
              {dockerDesktopOnline === true
                ? "online"
                : dockerDesktopOnline === false
                  ? "offline"
                  : "unknown"}
            </span>
            {dockerDesktopError && (
              <span className="text-muted-foreground text-xs">
                {dockerDesktopError}
              </span>
            )}
          </div>

          {loading ? (
            <div className="text-muted-foreground flex items-center gap-2 text-sm">
              <LoaderCircleIcon className="size-4 animate-spin" />
              Loading integrations...
            </div>
          ) : (
            <ul className="divide-y rounded-md border">
              {sortedServices.map((service) => (
                <li
                  key={service.id}
                  className="grid grid-cols-1 items-center gap-3 p-4 md:grid-cols-[minmax(140px,1fr)_1fr_1fr_1fr_auto]"
                >
                  <div className="font-medium">{service.label}</div>
                  <div className="text-sm">
                    <span className="text-muted-foreground">Host: </span>
                    {service.host ?? "N/A"}
                  </div>
                  <div className="text-sm">
                    <span className="text-muted-foreground">Port: </span>
                    {service.port ?? "N/A"}
                  </div>
                  <div className="text-sm">
                    <span className="text-muted-foreground">Docker: </span>
                    <span
                      className={
                        service.docker_online ? "text-green-700" : "text-red-700"
                      }
                    >
                      {service.docker_online ? "online" : "offline"}
                    </span>
                  </div>
                  <div className="flex items-center justify-start gap-3 md:justify-end">
                    <span
                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs ${
                        service.healthy
                          ? "bg-green-100 text-green-700"
                          : "bg-red-100 text-red-700"
                      }`}
                    >
                      {service.healthy ? "online" : "offline"}
                    </span>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={
                        !service.can_start ||
                        service.healthy ||
                        startingId === service.id ||
                        startingAll ||
                        activeJobId !== null
                      }
                      onClick={() => void startService(service.id)}
                    >
                      {startingId === service.id ? (
                        <LoaderCircleIcon className="size-4 animate-spin" />
                      ) : (
                        <>
                          <PlayIcon className="mr-1.5 size-4" />
                          Start up
                        </>
                      )}
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}

          <div className="space-y-2">
            <p className="text-muted-foreground text-sm">All Docker services</p>
            {dockerServices.length === 0 ? (
              <p className="text-muted-foreground text-sm">
                No Docker containers found.
              </p>
            ) : (
              <ul className="divide-y rounded-md border">
                {dockerServices.map((item) => (
                  <li
                    key={item.name}
                    className="grid grid-cols-1 gap-2 p-3 text-sm md:grid-cols-[1fr_2fr_auto]"
                  >
                    <span className="font-medium">{item.name}</span>
                    <span className="text-muted-foreground">{item.status}</span>
                    <span
                      className={
                        item.online ? "text-green-700" : "text-red-700"
                      }
                    >
                      {item.online ? "online" : "offline"}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {message && (
            <p className="rounded-md border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700">
              {message}
            </p>
          )}
          {error && (
            <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </p>
          )}

          {startupJob && (
            <div className="space-y-2 rounded-md border p-3">
              <p className="text-sm font-medium">
                Startup job: {startupJob.id} ({startupJob.status})
              </p>
              {startupJob.steps.length > 0 && (
                <ul className="space-y-1 text-sm">
                  {startupJob.steps.map((step) => (
                    <li key={step.service_id} className="flex items-center gap-2">
                      <span className="font-medium">{step.service_id}</span>
                      <span className="text-muted-foreground">{step.phase}</span>
                      <span className="text-muted-foreground">{step.detail}</span>
                    </li>
                  ))}
                </ul>
              )}
              {startupJob.logs_tail.length > 0 && (
                <pre className="bg-muted max-h-44 overflow-auto rounded p-2 text-xs">
                  {startupJob.logs_tail.slice(-12).join("\n")}
                </pre>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
