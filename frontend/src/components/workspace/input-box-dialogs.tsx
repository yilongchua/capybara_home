"use client";

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
import { Textarea } from "@/components/ui/textarea";
import { useI18n } from "@/core/i18n/hooks";

export function MountFolderDialog({
  open,
  onOpenChange,
  value,
  onChange,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  value: string;
  onChange: (value: string) => void;
  onConfirm: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Mount Folder</DialogTitle>
          <DialogDescription>
            Enter the absolute path of the folder to mount. No files will be uploaded — the agent
            will access them directly by path.
          </DialogDescription>
        </DialogHeader>
        <Input
          placeholder="/Users/you/Desktop/my-folder"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") onConfirm();
          }}
          autoFocus
        />
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="button" onClick={onConfirm} disabled={!value.trim()}>
            Mount
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function FollowupConfirmDialog({
  open,
  onOpenChange,
  onReplace,
  onAppend,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onReplace: () => void;
  onAppend: () => void;
}) {
  const { t } = useI18n();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t.inputBox.followupConfirmTitle}</DialogTitle>
          <DialogDescription>{t.inputBox.followupConfirmDescription}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t.common.cancel}
          </Button>
          <Button variant="secondary" onClick={onAppend}>
            {t.inputBox.followupConfirmAppend}
          </Button>
          <Button onClick={onReplace}>{t.inputBox.followupConfirmReplace}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function RenameThreadDialog({
  open,
  onOpenChange,
  value,
  onChange,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  value: string;
  onChange: (value: string) => void;
  onConfirm: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Rename chat</DialogTitle>
          <DialogDescription>
            Enter a new chat title.
          </DialogDescription>
        </DialogHeader>
        <Input
          placeholder="New title"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") onConfirm();
          }}
          autoFocus
        />
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="button" onClick={onConfirm} disabled={!value.trim()}>
            Rename
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function AutoresearchDialog({
  open,
  onOpenChange,
  topic,
  endpointGoal,
  onTopicChange,
  onEndpointGoalChange,
  onConfirm,
  isSubmitting,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  topic: string;
  endpointGoal: string;
  onTopicChange: (value: string) => void;
  onEndpointGoalChange: (value: string) => void;
  onConfirm: () => void;
  isSubmitting?: boolean;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Start autoresearch</DialogTitle>
          <DialogDescription>
            Provide a research topic and endpoint goal.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Input
            placeholder="Topic"
            value={topic}
            onChange={(e) => onTopicChange(e.target.value)}
            autoFocus
          />
          <Textarea
            placeholder="Endpoint goal"
            value={endpointGoal}
            onChange={(e) => onEndpointGoalChange(e.target.value)}
            onKeyDown={(e) => {
              if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
                onConfirm();
              }
            }}
            className="min-h-24"
          />
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            type="button"
            onClick={onConfirm}
            disabled={!topic.trim() || !endpointGoal.trim() || isSubmitting}
          >
            {isSubmitting ? "Starting..." : "Start"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
