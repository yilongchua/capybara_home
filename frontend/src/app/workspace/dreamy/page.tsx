"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useThreads } from "@/core/threads/hooks";
import { isDreamyThread, titleOfThread } from "@/core/threads/utils";
import { formatTimeAgo } from "@/core/utils/datetime";

export default function DreamyPage() {
  const { data: threads } = useThreads();
  const [search, setSearch] = useState("");

  useEffect(() => {
    document.title = "Dreamy — Capybara";
  }, []);

  const filteredThreads = useMemo(() => {
    return threads?.filter((thread) => {
      if (!isDreamyThread(thread)) {
        return false;
      }
      const title = titleOfThread(thread).toLowerCase();
      return title.includes(search.toLowerCase());
    });
  }, [threads, search]);

  return (
    <WorkspaceContainer>
      <WorkspaceHeader></WorkspaceHeader>
      <WorkspaceBody>
        <div className="flex size-full flex-col">
          <header className="flex shrink-0 flex-col items-center gap-4 pt-8">
            <Input
              type="search"
              className="h-12 w-full max-w-(--container-width-md) text-xl"
              placeholder="Search Dreamy sessions..."
              autoFocus
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <Button asChild>
              <Link href="/workspace/dreamy/new">
                New Dreamy Session
              </Link>
            </Button>
          </header>
          <main className="min-h-0 flex-1">
            <ScrollArea className="size-full py-4">
              <div className="mx-auto flex size-full max-w-(--container-width-md) flex-col">
                {filteredThreads?.map((thread) => (
                  <Link
                    key={thread.thread_id}
                    href={`/workspace/dreamy/${thread.thread_id}`}
                  >
                    <div className="flex flex-col gap-2 border-b p-4">
                      <div>{titleOfThread(thread)}</div>
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
  );
}
