"use client";

import { useCallback, useState } from "react";
import { toast } from "sonner";

import { getBackendBaseURL } from "@/core/config";
import { api } from "@/core/workspace-io/api";

export interface UseThreadSteeringReturn {
  isSteering: boolean;
  steerDialogOpen: boolean;
  steerInput: string;
  setSteerDialogOpen: (open: boolean) => void;
  setSteerInput: (value: string) => void;
  handleSteer: () => Promise<void>;
}

export function useThreadSteering(threadId: string): UseThreadSteeringReturn {
  const [isSteering, setIsSteering] = useState(false);
  const [steerDialogOpen, setSteerDialogOpen] = useState(false);
  const [steerInput, setSteerInput] = useState("");

  const handleSteer = useCallback(async () => {
    const message = steerInput.trim();
    if (!message) {
      toast.error("Steering message cannot be empty.");
      return;
    }

    setIsSteering(true);
    try {
      const response = await fetch(`${getBackendBaseURL()}${api.threads.steer(threadId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
      });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      setSteerDialogOpen(false);
      setSteerInput("");
      toast.success("Steering will be applied on the next model turn.");
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "Failed to set steering.";
      toast.error(errorMessage);
    } finally {
      setIsSteering(false);
    }
  }, [steerInput, threadId]);

  return {
    isSteering,
    steerDialogOpen,
    steerInput,
    setSteerDialogOpen,
    setSteerInput,
    handleSteer,
  };
}
