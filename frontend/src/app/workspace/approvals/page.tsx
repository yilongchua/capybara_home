"use client";

import { useEffect } from "react";

import { ApprovalCard } from "@/components/workspace/approvals/approval-card";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useApprovals, useProposalApprovals } from "@/core/control-plane";
import { useI18n } from "@/core/i18n/hooks";

export default function ApprovalsPage() {
  const { t } = useI18n();
  const { approvals, isLoading } = useApprovals({ refetchInterval: 15_000 });
  const { proposals } = useProposalApprovals({ refetchInterval: 15_000 });
  const pendingApprovals = approvals.filter((item) => item.status === "pending");

  useEffect(() => {
    document.title = `${t.pages.approvals} - ${t.pages.appName}`;
  }, [t.pages.appName, t.pages.approvals]);

  const pendingCount =
    pendingApprovals.length +
    proposals.filter((item) => item.status === "pending").length;

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody>
        <div className="flex size-full flex-col overflow-y-auto">
          <div className="border-b px-6 py-4">
            <h1 className="text-xl font-semibold">Approvals</h1>
            <p className="text-muted-foreground mt-0.5 text-sm">
              {pendingCount > 0
                ? `${pendingCount} pending approval${pendingCount !== 1 ? "s" : ""}`
                : "No pending approvals"}
            </p>
          </div>

          <div className="flex-1 p-6">
            {isLoading ? (
              <p className="text-muted-foreground text-sm">Loading…</p>
            ) : pendingApprovals.length === 0 ? (
              <div className="text-muted-foreground flex h-32 items-center justify-center text-sm">
                No pending approvals
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {pendingApprovals.map((approval) => (
                  <ApprovalCard key={approval.id} approval={approval} />
                ))}
              </div>
            )}
          </div>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
