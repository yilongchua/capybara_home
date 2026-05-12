import {
  createContext,
  useCallback,
  useContext,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";

import type { Subtask } from "./types";

export interface SubtaskContextValue {
  tasks: Record<string, Subtask>;
  setTasks: Dispatch<SetStateAction<Record<string, Subtask>>>;
}

export const SubtaskContext = createContext<SubtaskContextValue>({
  tasks: {},
  setTasks: () => {
    /* noop */
  },
});

export function SubtasksProvider({ children }: { children: React.ReactNode }) {
  const [tasks, setTasks] = useState<Record<string, Subtask>>({});
  return (
    <SubtaskContext.Provider value={{ tasks, setTasks }}>
      {children}
    </SubtaskContext.Provider>
  );
}

export function useSubtaskContext() {
  const context = useContext(SubtaskContext);
  if (context === undefined) {
    throw new Error(
      "useSubtaskContext must be used within a SubtaskContext.Provider",
    );
  }
  return context;
}

export function useSubtask(id: string) {
  const { tasks } = useSubtaskContext();
  return tasks[id];
}

export function useUpdateSubtask() {
  const { setTasks } = useSubtaskContext();

  const resolveStatus = (
    prevStatus: Subtask["status"] | undefined,
    nextStatus: Subtask["status"],
  ): Subtask["status"] => {
    if ((prevStatus === "completed" || prevStatus === "failed") && nextStatus === "in_progress") {
      return prevStatus;
    }
    return nextStatus;
  };

  const updateSubtask = useCallback(
    (task: Partial<Subtask> & { id: string }) => {
      setTasks((prev) => {
        const prevTask = prev[task.id];
        const nextTask = {
          ...prevTask,
          ...task,
        } as Subtask;
        nextTask.status = resolveStatus(prevTask?.status, nextTask.status);
        if (nextTask.status === "in_progress" && prevTask?.completed_at) {
          nextTask.completed_at = prevTask.completed_at;
        }

        if (
          prevTask?.status === nextTask.status &&
          prevTask.subagent_type === nextTask.subagent_type &&
          prevTask.description === nextTask.description &&
          prevTask.prompt === nextTask.prompt &&
          prevTask.result === nextTask.result &&
          prevTask.error === nextTask.error &&
          prevTask.latestMessage === nextTask.latestMessage &&
          prevTask.started_at === nextTask.started_at &&
          prevTask.updated_at === nextTask.updated_at &&
          prevTask.completed_at === nextTask.completed_at
        ) {
          return prev;
        }

        return {
          ...prev,
          [task.id]: nextTask,
        };
      });
    },
    [setTasks],
  );
  return updateSubtask;
}
