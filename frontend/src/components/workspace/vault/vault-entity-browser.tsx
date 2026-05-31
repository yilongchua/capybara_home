"use client";

import { ChevronDownIcon, ChevronRightIcon, Loader2Icon, SearchIcon, TrashIcon, UndoIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Textarea } from "@/components/ui/textarea";
import {
  useDismissVaultEntity,
  useRestoreVaultEntityDismissal,
  useStartVaultEntityAutoresearch,
  useVaultEntityBrowser,
  useVaultEntityDismissals,
} from "@/core/control-plane";
import type {
  VaultEntityBrowserItem,
  VaultEntityConceptItem,
  VaultEntitySourceItem,
} from "@/core/control-plane";

const DEFAULT_GOAL_TEMPLATE = "Expand vault coverage of {entity} with diverse, high-quality sources.";

function HubAndSpoke({ entity }: { entity: VaultEntityBrowserItem }) {
  const width = 576;
  const height = 368;
  const cx = width / 2;
  const cy = height / 2;
  const conceptRadius = 140;

  const concepts = entity.concepts;
  const conceptCount = concepts.length;

  const conceptPositions = concepts.map((concept, index) => {
    const angle = conceptCount === 0 ? 0 : (index / conceptCount) * Math.PI * 2 - Math.PI / 2;
    return {
      ...concept,
      x: cx + Math.cos(angle) * conceptRadius,
      y: cy + Math.sin(angle) * conceptRadius,
    };
  });

  const truncate = (text: string, max = 28) =>
    text.length > max ? `${text.slice(0, max)}…` : text;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="h-full w-full"
      role="img"
      aria-label={`Hub-and-spoke for entity ${entity.label}`}
      preserveAspectRatio="xMidYMid meet"
    >
      {conceptPositions.map((c) => (
        <line
          key={`c-${c.slug}`}
          x1={cx}
          y1={cy}
          x2={c.x}
          y2={c.y}
          stroke="#1d4ed8"
          strokeOpacity={0.3}
          strokeWidth={1.25}
        />
      ))}

      <g>
        <circle cx={cx} cy={cy} r={22} fill="#7c3aed" />
        <text
          x={cx}
          y={cy + 4}
          textAnchor="middle"
          fontSize={10}
          fontWeight={600}
          fill="white"
        >
          {truncate(entity.label, 14)}
        </text>
      </g>

      {conceptPositions.map((c) => {
        const labelOnLeft = c.x < cx;
        return (
          <g key={`cg-${c.slug}`}>
            <title>{c.label}</title>
            <circle cx={c.x} cy={c.y} r={5} fill="#1d4ed8" fillOpacity={0.9} />
            <text
              x={c.x + (labelOnLeft ? -8 : 8)}
              y={c.y + 3}
              textAnchor={labelOnLeft ? "end" : "start"}
              fontSize={9}
              fill="currentColor"
              fillOpacity={0.85}
            >
              {truncate(c.label, 22)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function EntityListRow({
  entity,
  selected,
  onClick,
  showActions,
  onResearch,
  onDismiss,
}: {
  entity: VaultEntityBrowserItem;
  selected: boolean;
  onClick: () => void;
  showActions: boolean;
  onResearch?: () => void;
  onDismiss?: () => void;
}) {
  return (
    <div
      className={`flex items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-muted ${
        selected ? "bg-muted font-medium" : ""
      }`}
    >
      <button
        type="button"
        onClick={onClick}
        className="flex min-w-0 flex-1 items-center gap-2 text-left"
      >
        <span className="inline-flex h-5 min-w-[20px] items-center justify-center rounded bg-muted-foreground/15 px-1 text-[10px] tabular-nums">
          {entity.degree}
        </span>
        <span className="truncate" title={entity.label}>
          {entity.label}
        </span>
      </button>
      {showActions ? (
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            className="rounded p-1 hover:bg-background"
            title="Research deeper (autoresearch)"
            aria-label="Research deeper"
            onClick={onResearch}
          >
            <SearchIcon className="size-3.5" />
          </button>
          <button
            type="button"
            className="rounded p-1 hover:bg-background"
            title="Not an entity / merge"
            aria-label="Dismiss or merge"
            onClick={onDismiss}
          >
            <TrashIcon className="size-3.5" />
          </button>
        </div>
      ) : null}
    </div>
  );
}

export function VaultEntityBrowser({
  onSourceOpen,
}: {
  onSourceOpen?: (sourcePathOrId: string) => void;
}) {
  // The entity-browser payload is large, so poll on a slow cadence (3× slower than
  // the old 20s default) — enough to surface background writes while the tab is open
  // without the previous churn; the hook also refreshes on "vault" events + tab focus.
  const { entityBrowser, isLoading } = useVaultEntityBrowser({ top: 15, bottom: 10, criticalMaxDegree: 2, refetchInterval: 60_000 });
  const { dismissals } = useVaultEntityDismissals();
  const dismissMutation = useDismissVaultEntity();
  const restoreMutation = useRestoreVaultEntityDismissal();
  const autoresearchMutation = useStartVaultEntityAutoresearch();

  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [criticalCollapsed, setCriticalCollapsed] = useState(false);
  const [dismissedCollapsed, setDismissedCollapsed] = useState(true);

  const [dismissDialog, setDismissDialog] = useState<{
    entity: VaultEntityBrowserItem;
    reason: string;
    aliasFor: string;
  } | null>(null);
  const [researchDialog, setResearchDialog] = useState<{
    entity: VaultEntityBrowserItem;
    goal: string;
  } | null>(null);

  const allEntities = useMemo(() => {
    if (!entityBrowser) return [];
    const seen = new Set<string>();
    const combined: VaultEntityBrowserItem[] = [];
    for (const list of [entityBrowser.top, entityBrowser.critical_gaps]) {
      for (const entry of list) {
        if (!seen.has(entry.slug)) {
          seen.add(entry.slug);
          combined.push(entry);
        }
      }
    }
    return combined;
  }, [entityBrowser]);

  const aliasCandidates = useMemo(
    () =>
      allEntities
        .map((entry) => ({ slug: entry.slug, label: entry.label }))
        .sort((a, b) => a.label.localeCompare(b.label)),
    [allEntities],
  );

  const selectedEntity = useMemo(() => {
    if (!selectedSlug) return null;
    return allEntities.find((entry) => entry.slug === selectedSlug) ?? null;
  }, [allEntities, selectedSlug]);

  const fallbackEntity = entityBrowser?.top[0] ?? entityBrowser?.critical_gaps[0] ?? null;
  const displayEntity = selectedEntity ?? fallbackEntity;

  const handleResearch = (entity: VaultEntityBrowserItem) => {
    setResearchDialog({
      entity,
      goal: DEFAULT_GOAL_TEMPLATE.replace("{entity}", entity.label),
    });
  };

  const submitResearch = () => {
    if (!researchDialog) return;
    const { entity, goal } = researchDialog;
    autoresearchMutation.mutate(
      {
        slug: entity.slug,
        request: { label: entity.label, endpoint_goal: goal },
      },
      {
        onSuccess: (data) => {
          toast.success(
            data.objective_id
              ? `Autoresearch queued for "${entity.label}".`
              : `Autoresearch started for "${entity.label}".`,
          );
          setResearchDialog(null);
        },
        onError: (error) => toast.error(error.message),
      },
    );
  };

  const submitDismiss = () => {
    if (!dismissDialog) return;
    const { entity, reason, aliasFor } = dismissDialog;
    dismissMutation.mutate(
      {
        slug: entity.slug,
        request: {
          reason: reason.trim() || undefined,
          alias_for: aliasFor.trim() || null,
        },
      },
      {
        onSuccess: () => {
          toast.success(
            aliasFor.trim()
              ? `"${entity.label}" merged into ${aliasFor.trim()}.`
              : `"${entity.label}" dismissed.`,
          );
          if (selectedSlug === entity.slug) setSelectedSlug(null);
          setDismissDialog(null);
        },
        onError: (error) => toast.error(error.message),
      },
    );
  };

  const counts = entityBrowser?.counts ?? {};
  const criticalMaxDegree = Number(counts.critical_max_degree ?? 2);

  return (
    <div className="flex min-h-0 flex-1 gap-3 text-xs">
      <div className="flex w-72 min-w-0 shrink-0 flex-col gap-3 overflow-y-auto rounded border p-2">
        <div className="text-muted-foreground">
          {isLoading ? (
            <span className="flex items-center gap-1">
              <Loader2Icon className="size-3.5 animate-spin" /> Loading entities…
            </span>
          ) : (
            <span>
              {Number(counts.total_entities ?? 0)} entities · {Number(counts.dismissed ?? 0)} dismissed
            </span>
          )}
        </div>

        {/* Most connected */}
        <section>
          <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Most connected
          </h3>
          <div className="space-y-0.5">
            {(entityBrowser?.top ?? []).length === 0 ? (
              <p className="px-2 py-1 text-muted-foreground">No entities yet.</p>
            ) : (
              entityBrowser?.top.map((entry) => (
                <EntityListRow
                  key={`top-${entry.slug}`}
                  entity={entry}
                  selected={selectedSlug === entry.slug}
                  onClick={() => setSelectedSlug(entry.slug)}
                  showActions={false}
                />
              ))
            )}
          </div>
        </section>

        {/* Critical gaps */}
        <section>
          <button
            type="button"
            onClick={() => setCriticalCollapsed((value) => !value)}
            className="mb-1 flex w-full items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground"
          >
            {criticalCollapsed ? (
              <ChevronRightIcon className="size-3" />
            ) : (
              <ChevronDownIcon className="size-3" />
            )}
            <span>
              Critical gaps (degree ≤ {criticalMaxDegree}) ·{" "}
              {entityBrowser?.critical_gaps.length ?? 0}
            </span>
          </button>
          {!criticalCollapsed ? (
            <div className="space-y-0.5">
              {(entityBrowser?.critical_gaps ?? []).length === 0 ? (
                <p className="px-2 py-1 text-muted-foreground">
                  All entities have ≥ {criticalMaxDegree + 1} sources — coverage looks solid.
                </p>
              ) : (
                entityBrowser?.critical_gaps.map((entry) => (
                  <EntityListRow
                    key={`crit-${entry.slug}`}
                    entity={entry}
                    selected={selectedSlug === entry.slug}
                    onClick={() => setSelectedSlug(entry.slug)}
                    showActions
                    onResearch={() => handleResearch(entry)}
                    onDismiss={() => setDismissDialog({ entity: entry, reason: "", aliasFor: "" })}
                  />
                ))
              )}
            </div>
          ) : null}
        </section>

        {/* Dismissed */}
        <section>
          <button
            type="button"
            onClick={() => setDismissedCollapsed((value) => !value)}
            className="mb-1 flex w-full items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground"
          >
            {dismissedCollapsed ? (
              <ChevronRightIcon className="size-3" />
            ) : (
              <ChevronDownIcon className="size-3" />
            )}
            <span>Dismissed · {dismissals.length}</span>
          </button>
          {!dismissedCollapsed ? (
            <div className="space-y-0.5">
              {dismissals.length === 0 ? (
                <p className="px-2 py-1 text-muted-foreground">No dismissed entities.</p>
              ) : (
                dismissals.map((item) => (
                  <div
                    key={`dismissed-${item.slug}`}
                    className="flex items-center gap-2 rounded px-2 py-1 text-muted-foreground"
                  >
                    <span className="min-w-0 flex-1 truncate" title={item.reason || item.label}>
                      {item.label}
                      {item.alias_for ? ` → ${item.alias_for}` : ""}
                    </span>
                    <button
                      type="button"
                      className="rounded p-1 hover:bg-background"
                      title="Restore"
                      aria-label="Restore dismissal"
                      onClick={() =>
                        restoreMutation.mutate(item.slug, {
                          onSuccess: () => toast.success(`Restored "${item.label}".`),
                          onError: (error) => toast.error(error.message),
                        })
                      }
                    >
                      <UndoIcon className="size-3.5" />
                    </button>
                  </div>
                ))
              )}
            </div>
          ) : null}
        </section>
      </div>

      {/* Detail panel */}
      <div className="flex min-h-0 flex-1 flex-col rounded border p-3">
        {displayEntity ? (
          <>
            <div className="mb-2 flex shrink-0 flex-wrap items-baseline justify-between gap-2">
              <div>
                <h2 className="text-sm font-semibold">{displayEntity.label}</h2>
                <p className="text-muted-foreground">
                  {displayEntity.degree} source{displayEntity.degree === 1 ? "" : "s"} ·{" "}
                  {displayEntity.concepts.length} concept
                  {displayEntity.concepts.length === 1 ? "" : "s"}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Button size="sm" variant="outline" onClick={() => handleResearch(displayEntity)}>
                  <SearchIcon className="mr-1 size-3.5" /> Research deeper
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    setDismissDialog({ entity: displayEntity, reason: "", aliasFor: "" })
                  }
                >
                  <TrashIcon className="mr-1 size-3.5" /> Dismiss / merge
                </Button>
              </div>
            </div>
            <ResizablePanelGroup
              id="vault-entity-detail-panel-group"
              orientation="vertical"
              className="min-h-0 flex-1"
            >
              <ResizablePanel
                id="vault-entity-graph-panel"
                defaultSize={55}
                minSize={20}
                className="rounded border bg-background/60"
              >
                <HubAndSpoke entity={displayEntity} />
              </ResizablePanel>
              <ResizableHandle
                id="vault-entity-detail-handle"
                withHandle
                className="my-2 bg-transparent"
              />
              <ResizablePanel
                id="vault-entity-lists-panel"
                defaultSize={45}
                minSize={15}
                className="min-h-0"
              >
                <div className="grid h-full min-h-0 gap-2 md:grid-cols-2">
                  <ListSection
                    title="Sources"
                    items={displayEntity.sources.map((source: VaultEntitySourceItem) => ({
                      key: source.source_id,
                      primary: source.title || source.source_id,
                      secondary: source.url,
                      onClick: onSourceOpen ? () => onSourceOpen(source.source_id) : undefined,
                    }))}
                  />
                  <ListSection
                    title="Co-occurring concepts"
                    items={displayEntity.concepts.map((concept: VaultEntityConceptItem) => ({
                      key: concept.slug,
                      primary: concept.label,
                      secondary: concept.slug,
                    }))}
                  />
                </div>
              </ResizablePanel>
            </ResizablePanelGroup>
          </>
        ) : (
          <p className="text-muted-foreground">
            {isLoading ? "Loading entities…" : "No entities yet. Run ingest to populate the vault."}
          </p>
        )}
      </div>

      {/* Research dialog */}
      <Dialog
        open={researchDialog !== null}
        onOpenChange={(open) => !open && setResearchDialog(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Research deeper: {researchDialog?.entity.label}</DialogTitle>
            <DialogDescription>
              Edit the research goal and queue an autoresearch run. The placeholder is a starting
              point — make it specific to what you want to learn about this entity.
            </DialogDescription>
          </DialogHeader>
          <Textarea
            value={researchDialog?.goal ?? ""}
            onChange={(event) =>
              setResearchDialog((current) =>
                current ? { ...current, goal: event.target.value } : current,
              )
            }
            className="min-h-[100px]"
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setResearchDialog(null)}>
              Cancel
            </Button>
            <Button onClick={submitResearch} disabled={autoresearchMutation.isPending}>
              {autoresearchMutation.isPending ? (
                <Loader2Icon className="mr-1 size-4 animate-spin" />
              ) : null}
              Queue autoresearch
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Dismiss dialog */}
      <Dialog
        open={dismissDialog !== null}
        onOpenChange={(open) => !open && setDismissDialog(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Dismiss or merge: {dismissDialog?.entity.label}</DialogTitle>
            <DialogDescription>
              Dismiss to mark as not-an-entity (e.g. extraction noise), or merge into another
              entity by selecting an alias. Affected source records will be rewritten.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <label className="block text-xs">
              <span className="mb-1 block font-medium">Reason (optional)</span>
              <Input
                value={dismissDialog?.reason ?? ""}
                onChange={(event) =>
                  setDismissDialog((current) =>
                    current ? { ...current, reason: event.target.value } : current,
                  )
                }
                placeholder="e.g. tokenizer noise, duplicate of Apple Inc"
              />
            </label>
            <label className="block text-xs">
              <span className="mb-1 block font-medium">Merge into (optional)</span>
              <Input
                value={dismissDialog?.aliasFor ?? ""}
                onChange={(event) =>
                  setDismissDialog((current) =>
                    current ? { ...current, aliasFor: event.target.value } : current,
                  )
                }
                placeholder="Type an entity label or slug"
                list="vault-entity-alias-candidates"
              />
              <datalist id="vault-entity-alias-candidates">
                {aliasCandidates.map((candidate) => (
                  <option
                    key={candidate.slug}
                    value={candidate.slug}
                    label={candidate.label}
                  />
                ))}
              </datalist>
              <span className="mt-1 block text-muted-foreground">
                Leave blank to dismiss without merge.
              </span>
            </label>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDismissDialog(null)}>
              Cancel
            </Button>
            <Button onClick={submitDismiss} disabled={dismissMutation.isPending}>
              {dismissMutation.isPending ? (
                <Loader2Icon className="mr-1 size-4 animate-spin" />
              ) : null}
              {dismissDialog?.aliasFor.trim() ? "Merge" : "Dismiss"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function ListSection({
  title,
  items,
}: {
  title: string;
  items: Array<{ key: string; primary: string; secondary?: string; onClick?: () => void }>;
}) {
  return (
    <div className="flex min-h-0 flex-col rounded border bg-background/60 p-2">
      <h3 className="mb-1 shrink-0 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        {title} · {items.length}
      </h3>
      {items.length === 0 ? (
        <p className="px-1 py-1 text-muted-foreground">None.</p>
      ) : (
        <ul className="min-h-0 flex-1 space-y-0.5 overflow-y-auto">
          {items.map((item) => (
            <li key={item.key}>
              {item.onClick ? (
                <button
                  type="button"
                  onClick={item.onClick}
                  className="block w-full truncate rounded px-1 py-0.5 text-left hover:bg-muted"
                  title={item.secondary ?? item.primary}
                >
                  {item.primary}
                </button>
              ) : (
                <span
                  className="block truncate rounded px-1 py-0.5"
                  title={item.secondary ?? item.primary}
                >
                  {item.primary}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
