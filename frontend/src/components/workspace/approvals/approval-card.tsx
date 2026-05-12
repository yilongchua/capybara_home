"use client";

import { CheckIcon, DatabaseIcon, XIcon } from "lucide-react";
import { useState } from "react";


import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useResolveApproval } from "@/core/control-plane";
import { type ApprovalRequest } from "@/core/control-plane/types";

function StatusBadge({ status }: { status: ApprovalRequest["status"] }) {
  const config: Record<
    ApprovalRequest["status"],
    { label: string; className: string }
  > = {
    pending: {
      label: "Pending",
      className:
        "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400",
    },
    approved: {
      label: "Approved",
      className:
        "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400",
    },
    rejected: {
      label: "Rejected",
      className:
        "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400",
    },
    expired: {
      label: "Expired",
      className: "bg-muted text-muted-foreground",
    },
  };
  const { label, className } = config[status];
  return (
    <Badge variant="outline" className={className}>
      {label}
    </Badge>
  );
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function ApprovalCard({ approval }: { approval: ApprovalRequest }) {
  const { mutate: resolve, isPending } = useResolveApproval();
  const [confirming, setConfirming] = useState<"approve" | "reject" | null>(
    null,
  );

  const isPendingStatus = approval.status === "pending";
  const itemCount = approval.metadata.queued_item_count as number | undefined;
  const sampleTitles = approval.metadata.sample_titles as
    | string[]
    | undefined;

  const displayTitle = `Websearch→KV Ingest${itemCount != null ? ` - ${itemCount} items` : ""}`;

  function handleResolve(approve: boolean) {
    resolve(
      { approvalId: approval.id, request: { approve, auto_start: approve } },
      { onSettled: () => setConfirming(null) },
    );
  }

  return (
    <Card className="flex flex-col">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <div className="bg-primary/10 text-primary flex h-9 w-9 shrink-0 items-center justify-center rounded-lg">
              <DatabaseIcon className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <CardTitle className="text-sm leading-snug">
                {displayTitle}
              </CardTitle>
              <p className="text-muted-foreground mt-0.5 text-xs">
                {formatDate(approval.requested_at)}
              </p>
            </div>
          </div>
          <StatusBadge status={approval.status} />
        </div>
      </CardHeader>

      {sampleTitles && sampleTitles.length > 0 && (
        <CardContent className="flex-1 pt-0 pb-3">
          <ul className="text-muted-foreground space-y-1 text-sm">
            {sampleTitles.map((title, i) => (
              <li key={i} className="flex gap-1.5">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-current" />
                <span className="line-clamp-2">{title}</span>
              </li>
            ))}
          </ul>
        </CardContent>
      )}

      {isPendingStatus && (
        <CardFooter className="pt-0">
          {confirming === null ? (
            <div className="flex w-full gap-2">
              <Button
                size="sm"
                className="flex-1"
                onClick={() => setConfirming("approve")}
                disabled={isPending}
              >
                <CheckIcon className="mr-1.5 h-3.5 w-3.5" />
                Approve
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="flex-1"
                onClick={() => setConfirming("reject")}
                disabled={isPending}
              >
                <XIcon className="mr-1.5 h-3.5 w-3.5" />
                Reject
              </Button>
            </div>
          ) : (
            <div className="flex w-full flex-col gap-2">
              <p className="text-muted-foreground text-xs">
                {confirming === "approve"
                  ? "Approve and start vault ingestion?"
                  : "Reject and discard queued results?"}
              </p>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant={confirming === "approve" ? "default" : "destructive"}
                  className="flex-1"
                  onClick={() => handleResolve(confirming === "approve")}
                  disabled={isPending}
                >
                  {isPending ? "Processing…" : "Confirm"}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="flex-1"
                  onClick={() => setConfirming(null)}
                  disabled={isPending}
                >
                  Cancel
                </Button>
              </div>
            </div>
          )}
        </CardFooter>
      )}

      {!isPendingStatus && approval.resolved_at && (
        <CardFooter className="pt-0">
          <p className="text-muted-foreground text-xs">
            Resolved {formatDate(approval.resolved_at)}
            {approval.resolution_note ? ` · ${approval.resolution_note}` : ""}
          </p>
        </CardFooter>
      )}
    </Card>
  );
}
