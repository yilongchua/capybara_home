"use client";

import { Trash2 } from "lucide-react";
import Link from "next/link";
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
import { useDeleteAllThreads, useThreads } from "@/core/threads/hooks";
import { pathOfThread, titleOfThread } from "@/core/threads/utils";
import { formatTimeAgo } from "@/core/utils/datetime";

export default function ChatsPage() {
  const { t } = useI18n();
  const { data: threads } = useThreads();
  const [search, setSearch] = useState("");
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const deleteAllMutation = useDeleteAllThreads();

  useEffect(() => {
    document.title = `${t.pages.chats} - ${t.pages.appName}`;
  }, [t.pages.chats, t.pages.appName]);

  const filteredThreads = useMemo(() => {
    return threads?.filter((thread) => {
      return titleOfThread(thread).toLowerCase().includes(search.toLowerCase());
    });
  }, [threads, search]);

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
                    <Link
                      key={thread.thread_id}
                      href={pathOfThread(thread.thread_id)}
                    >
                      <div className="flex flex-col gap-2 border-b p-4">
                        <div>
                          <div>{titleOfThread(thread)}</div>
                        </div>
                        {thread.updated_at && (
                          <div className="text-muted-foreground text-sm">
                            {formatTimeAgo(thread.updated_at)}
                          </div>
                        )}
                      </div>
                    </Link>
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
                deleteAllMutation.mutate();
                setShowDeleteDialog(false);
              }}
              disabled={deleteAllMutation.isPending}
            >
              {deleteAllMutation.isPending ? "Deleting..." : t.common.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
