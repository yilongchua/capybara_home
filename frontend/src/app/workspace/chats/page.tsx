"use client";

import { Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import { useDeleteAllThreads, useDeleteThread, useThreads } from "@/core/threads/hooks";
import { pathOfThread, titleOfThread } from "@/core/threads/utils";
import { formatTimeAgo } from "@/core/utils/datetime";

export default function ChatsPage() {
  const { t } = useI18n();
  const router = useRouter();
  const { data: threads } = useThreads();
  const [search, setSearch] = useState("");
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [threadIdToDelete, setThreadIdToDelete] = useState<string | null>(null);
  const deleteAllMutation = useDeleteAllThreads();
  const deleteThreadMutation = useDeleteThread();

  useEffect(() => {
    document.title = `${t.pages.chats} - ${t.pages.appName}`;
  }, [t.pages.chats, t.pages.appName]);

  const filteredThreads = useMemo(() => {
    return threads?.filter((thread) => {
      return titleOfThread(thread).toLowerCase().includes(search.toLowerCase());
    });
  }, [threads, search]);

  const threadPendingDelete = useMemo(
    () => filteredThreads?.find((thread) => thread.thread_id === threadIdToDelete) ?? null,
    [filteredThreads, threadIdToDelete],
  );

  return (
    <>
      <WorkspaceContainer>
        <WorkspaceHeader></WorkspaceHeader>
        <WorkspaceBody>
          <div className="flex size-full flex-col">
            <header className="flex shrink-0 items-center justify-center pt-8">
              <Input
                type="search"
                className="h-12 w-full max-w-(--container-width-md) text-xl"
                placeholder={t.chats.searchChats}
                autoFocus
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </header>
            <div className="flex justify-end px-4 py-2">
              <Button
                variant="ghost"
                size="sm"
                className="text-destructive hover:text-destructive"
                disabled={deleteAllMutation.isPending}
                onClick={() => setShowDeleteDialog(true)}
              >
                <Trash2 className="mr-2 size-4" />
                {t.chats.deleteAllChats}
              </Button>
            </div>
            <main className="min-h-0 flex-1">
              <ScrollArea className="size-full py-4">
                <div className="mx-auto flex size-full max-w-(--container-width-md) flex-col">
                  {filteredThreads?.map((thread) => (
                    <div
                      key={thread.thread_id}
                      className="flex items-center gap-3 border-b p-4"
                    >
                      <Link
                        href={pathOfThread(thread.thread_id)}
                        className="min-w-0 flex-1"
                      >
                        <div className="flex flex-col gap-2">
                          <div>{titleOfThread(thread)}</div>
                          {thread.updated_at && (
                            <div className="text-muted-foreground text-sm">
                              {formatTimeAgo(thread.updated_at)}
                            </div>
                          )}
                        </div>
                      </Link>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="text-destructive hover:text-destructive"
                        aria-label={t.common.delete}
                        disabled={deleteThreadMutation.isPending}
                        onClick={() => setThreadIdToDelete(thread.thread_id)}
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                  ))}
                </div>
              </ScrollArea>
            </main>
          </div>
        </WorkspaceBody>
      </WorkspaceContainer>

      <Dialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t.chats.deleteAllChats}</DialogTitle>
            <DialogDescription>
              {t.chats.deleteAllChatsConfirm}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button
              variant="outline"
              onClick={() => setShowDeleteDialog(false)}
              disabled={deleteAllMutation.isPending}
            >
              {t.common.cancel || "Cancel"}
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                deleteAllMutation.mutate(undefined, {
                  onSuccess: (result) => {
                    if (result.failed_thread_ids.length === 0) {
                      router.push("/workspace/chats/new");
                    }
                  },
                });
                setShowDeleteDialog(false);
              }}
              disabled={deleteAllMutation.isPending}
            >
              {deleteAllMutation.isPending ? "Deleting..." : t.common.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={threadIdToDelete !== null}
        onOpenChange={(open) => {
          if (!open) {
            setThreadIdToDelete(null);
          }
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t.common.delete}</DialogTitle>
            <DialogDescription>
              {t.chats.deleteChatConfirm}
            </DialogDescription>
          </DialogHeader>
          {threadPendingDelete ? (
            <div className="text-sm font-medium">{titleOfThread(threadPendingDelete)}</div>
          ) : null}
          <DialogFooter className="gap-2 sm:gap-0">
            <Button
              variant="outline"
              onClick={() => setThreadIdToDelete(null)}
              disabled={deleteThreadMutation.isPending}
            >
              {t.common.cancel || "Cancel"}
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                if (!threadIdToDelete) {
                  return;
                }
                deleteThreadMutation.mutate(
                  { threadId: threadIdToDelete },
                  {
                    onSuccess: () => {
                      setThreadIdToDelete(null);
                    },
                  },
                );
              }}
              disabled={deleteThreadMutation.isPending}
            >
              {deleteThreadMutation.isPending ? "Deleting..." : t.common.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
