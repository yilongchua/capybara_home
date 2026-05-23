"use client";

import { usePathname } from "next/navigation";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { deleteVaultKnowledgeGraph } from "@/core/control-plane/api";
import { useI18n } from "@/core/i18n/hooks";
import { useCompactions, useMemory, useMemoryMutations } from "@/core/memory/hooks";
import { formatTimeAgo } from "@/core/utils/datetime";

import { SettingsSection } from "./settings-section";

function useCurrentThreadId() {
  const pathname = usePathname();
  return useMemo(() => {
    const match = /\/workspace\/chats\/([^/]+)/.exec(pathname);
    return match?.[1] ?? null;
  }, [pathname]);
}

export function MemorySettingsPage() {
  const { t } = useI18n();
  const threadId = useCurrentThreadId();
  const [newRule, setNewRule] = useState("");
  const [forgetThreadId, setForgetThreadId] = useState(threadId ?? "");

  const globalMemory = useMemory("global");
  const workspaceMemory = useMemory("workspace", threadId);
  const compactions = useCompactions(threadId);
  const globalMutations = useMemoryMutations("global");
  const workspaceMutations = useMemoryMutations("workspace", threadId);
  const [graphDeleting, setGraphDeleting] = useState(false);

  const loading = globalMemory.isLoading || workspaceMemory.isLoading;
  const global = globalMemory.memory;
  const workspace = workspaceMemory.memory;

  return (
    <SettingsSection title={t.settings.memory.title} description={t.settings.memory.description}>
      {loading ? <div className="text-sm text-muted-foreground">{t.common.loading}</div> : null}

      {global ? (
        <div className="rounded-lg border p-4 space-y-3">
          <div className="font-medium">Global Memory</div>
          <div className="text-xs text-muted-foreground">Last updated: {formatTimeAgo(global.lastUpdated)}</div>
          <EditableFacts
            facts={global.facts}
            onDelete={(factId) => globalMutations.removeFact.mutate(factId)}
            onSave={(factId, content, category, confidence) =>
              globalMutations.updateFact.mutate({
                factId,
                payload: { content, category, confidence, source: "memory-ui" },
              })
            }
          />
          <RulesList
            rules={global.behaviorRules ?? []}
            onToggle={(ruleId, active) => globalMutations.editRule.mutate({ ruleId, payload: { active } })}
            onDelete={(ruleId) => globalMutations.removeRule.mutate(ruleId)}
          />
        </div>
      ) : null}

      {workspace ? (
        <div className="rounded-lg border p-4 space-y-3">
          <div className="font-medium">Workspace Memory</div>
          <div className="text-xs text-muted-foreground">
            Scope: {workspace.scope ?? "workspace"} ({workspace.scopeId ?? threadId ?? "n/a"})
          </div>
          <EditableFacts
            facts={workspace.facts}
            onDelete={(factId) => workspaceMutations.removeFact.mutate(factId)}
            onSave={(factId, content, category, confidence) =>
              workspaceMutations.updateFact.mutate({
                factId,
                payload: { content, category, confidence, source: "memory-ui" },
              })
            }
          />
          <RulesList
            rules={workspace.behaviorRules ?? []}
            onToggle={(ruleId, active) => workspaceMutations.editRule.mutate({ ruleId, payload: { active } })}
            onDelete={(ruleId) => workspaceMutations.removeRule.mutate(ruleId)}
          />
        </div>
      ) : null}

      <div className="rounded-lg border p-4 space-y-3">
        <div className="font-medium">Inject Behavior Rule</div>
        <div className="flex gap-2">
          <Input
            value={newRule}
            onChange={(e) => setNewRule(e.target.value)}
            placeholder="/memory always write all plans into markdown file"
          />
          <Button
            onClick={() => {
              if (!newRule.trim()) return;
              if (threadId) {
                workspaceMutations.addRule.mutate({ instruction: newRule.trim(), source: "memory-ui" });
              } else {
                globalMutations.addRule.mutate({ instruction: newRule.trim(), source: "memory-ui" });
              }
              setNewRule("");
            }}
          >
            Save
          </Button>
        </div>
      </div>

      <div className="rounded-lg border p-4 space-y-3">
        <div className="font-medium">Forget Thread Facts</div>
        <div className="flex gap-2">
          <Input value={forgetThreadId} onChange={(e) => setForgetThreadId(e.target.value)} placeholder="thread id" />
          <Button
            variant="secondary"
            onClick={() => {
              if (!forgetThreadId.trim()) return;
              workspaceMutations.forgetThread.mutate(forgetThreadId.trim());
            }}
            disabled={!threadId}
          >
            Forget
          </Button>
        </div>
      </div>

      <div className="rounded-lg border border-destructive/30 p-4 space-y-3">
        <div className="font-medium">Delete All Memory</div>
        <div className="text-sm text-muted-foreground">This permanently clears stored facts, rules, and summaries.</div>
        <div className="flex gap-2">
          <Button
            variant="destructive"
            onClick={() => {
              if (!window.confirm("Delete all global memory? This cannot be undone.")) return;
              globalMutations.clear.mutate();
            }}
            disabled={globalMutations.clear.isPending}
          >
            Delete Global Memory
          </Button>
          <Button
            variant="destructive"
            onClick={() => {
              if (!threadId) return;
              if (!window.confirm("Delete all workspace memory for this thread? This cannot be undone.")) return;
              workspaceMutations.clear.mutate();
            }}
            disabled={!threadId || workspaceMutations.clear.isPending}
          >
            Delete Workspace Memory
          </Button>
          <Button
            variant="destructive"
            onClick={async () => {
              if (
                !window.confirm(
                  "Delete the entire knowledge graph? This removes all sources, concepts, entities, and pending queue items. This cannot be undone.",
                )
              ) {
                return;
              }
              setGraphDeleting(true);
              try {
                await deleteVaultKnowledgeGraph();
              } catch (err) {
                window.alert(err instanceof Error ? err.message : "Failed to delete knowledge graph.");
              } finally {
                setGraphDeleting(false);
              }
            }}
            disabled={graphDeleting}
          >
            {graphDeleting ? "Deleting…" : "Delete Knowledge Graph"}
          </Button>
        </div>
        <div className="text-xs text-muted-foreground">
          Knowledge Graph removes all sources, concepts, entities, and queued ingest items from the vault.
        </div>
      </div>

      <div className="rounded-lg border p-4 space-y-3">
        <div className="font-medium">Compaction History</div>
        {!threadId ? <div className="text-sm text-muted-foreground">Open a chat thread to view compactions.</div> : null}
        {threadId && compactions.compactions.length === 0 ? (
          <div className="text-sm text-muted-foreground">No compaction entries yet.</div>
        ) : null}
        {threadId && compactions.compactions.length > 0 ? (
          <div className="space-y-2 text-sm">
            {compactions.compactions.slice(-20).reverse().map((entry, idx) => (
              <div key={idx} className="rounded border p-2">
                <div className="font-medium">{renderEntryValue(entry.trigger, "unknown trigger")}</div>
                <div className="text-xs text-muted-foreground">
                  compressed={renderEntryValue(entry.messages_compressed, "?")} kept={renderEntryValue(entry.messages_kept, "?")}
                </div>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </SettingsSection>
  );
}

type EditableFactsProps = {
  facts: Array<{
    id: string;
    content: string;
    category: string;
    confidence: number;
  }>;
  onSave: (factId: string, content: string, category: string, confidence: number) => void;
  onDelete: (factId: string) => void;
};

function EditableFacts({ facts, onSave, onDelete }: EditableFactsProps) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  if (!facts.length) {
    return <div className="text-sm text-muted-foreground">No facts.</div>;
  }
  return (
    <div className="space-y-2">
      {facts.map((fact) => {
        const value = drafts[fact.id] ?? fact.content;
        return (
          <div key={fact.id} className="rounded border p-2 space-y-2">
            <div className="text-xs text-muted-foreground">{fact.category}</div>
            <Input value={value} onChange={(e) => setDrafts((prev) => ({ ...prev, [fact.id]: e.target.value }))} />
            <div className="flex gap-2">
              <Button size="sm" onClick={() => onSave(fact.id, value, fact.category, fact.confidence)}>
                Save
              </Button>
              <Button size="sm" variant="destructive" onClick={() => onDelete(fact.id)}>
                Delete
              </Button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

type RulesListProps = {
  rules: Array<{
    id: string;
    instruction: string;
    active: boolean;
  }>;
  onToggle: (ruleId: string, active: boolean) => void;
  onDelete: (ruleId: string) => void;
};

function RulesList({ rules, onToggle, onDelete }: RulesListProps) {
  if (!rules.length) {
    return <div className="text-sm text-muted-foreground">No behavior rules.</div>;
  }
  return (
    <div className="space-y-2">
      {rules.map((rule) => (
        <div key={rule.id} className="rounded border p-2 flex items-center gap-2">
          <div className="flex-1 text-sm">{rule.instruction}</div>
          <Button size="sm" variant={rule.active ? "secondary" : "outline"} onClick={() => onToggle(rule.id, !rule.active)}>
            {rule.active ? "Active" : "Inactive"}
          </Button>
          <Button size="sm" variant="destructive" onClick={() => onDelete(rule.id)}>
            Delete
          </Button>
        </div>
      ))}
    </div>
  );
}

function renderEntryValue(value: unknown, fallback: string) {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}
