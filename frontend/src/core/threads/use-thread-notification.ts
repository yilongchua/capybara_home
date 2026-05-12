"use client";

import { useCallback } from "react";

import { useNotification } from "@/core/notification/hooks";
import { textOfMessage } from "@/core/threads/utils";

import type { AgentThreadState } from "./types";

const NOTIFICATION_PREVIEW_LENGTH = 200;

export function useThreadNotification() {
  const { showNotification } = useNotification();

  const onFinish = useCallback(
    (state: AgentThreadState) => {
      if (!document.hidden && document.hasFocus()) return;

      let body = "Conversation finished";
      const lastMessage = state.messages.at(-1);
      if (lastMessage) {
        const textContent = textOfMessage(lastMessage);
        if (textContent) {
          body =
            textContent.length > NOTIFICATION_PREVIEW_LENGTH
              ? textContent.substring(0, NOTIFICATION_PREVIEW_LENGTH) + "..."
              : textContent;
        }
      }
      showNotification(state.title, { body });
    },
    [showNotification],
  );

  return { onFinish };
}
