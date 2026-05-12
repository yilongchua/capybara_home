"use client";

import { ChevronDownIcon, FolderPlusIcon, PaperclipIcon } from "lucide-react";

import {
  PromptInputActionMenu,
  PromptInputActionMenuContent,
  PromptInputActionMenuItem,
  PromptInputActionMenuTrigger,
} from "@/components/ai-elements/prompt-input";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

export interface AttachmentPopupProps {
  onAttachFiles: () => void;
  onMountFolder: () => void;
  isPicking?: boolean;
  className?: string;
  triggerId?: string;
}

export function AttachmentPopup({
  onAttachFiles,
  onMountFolder,
  isPicking,
  className,
  triggerId,
}: AttachmentPopupProps) {
  const { t } = useI18n();
  return (
    <PromptInputActionMenu>
      <PromptInputActionMenuTrigger
        id={triggerId}
        aria-label={t.chatUI.attachmentPopup.tooltip}
        title={t.chatUI.attachmentPopup.tooltip}
        className={cn("gap-1 px-2!", className)}
      >
        <PaperclipIcon className="size-4" />
        <ChevronDownIcon className="size-3 opacity-60" />
      </PromptInputActionMenuTrigger>
      <PromptInputActionMenuContent align="start" className="w-56">
        <PromptInputActionMenuItem onSelect={onAttachFiles}>
          <PaperclipIcon className="mr-2 size-4" />
          <span>{t.chatUI.attachmentPopup.attachFiles}</span>
        </PromptInputActionMenuItem>
        <PromptInputActionMenuItem
          onSelect={onMountFolder}
          disabled={isPicking}
        >
          <FolderPlusIcon className="mr-2 size-4" />
          <span>
            {isPicking
              ? t.chatUI.attachmentPopup.picking
              : t.chatUI.attachmentPopup.mountFolder}
          </span>
        </PromptInputActionMenuItem>
      </PromptInputActionMenuContent>
    </PromptInputActionMenu>
  );
}
