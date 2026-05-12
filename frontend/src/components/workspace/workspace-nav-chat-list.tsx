"use client";

import { BookOpenIcon, BotIcon, CalendarClockIcon, CheckCheckIcon, MessagesSquare, PlugZapIcon, SparklesIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import {
  SidebarGroup,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";

export function WorkspaceNavChatList() {
  const { t } = useI18n();
  const pathname = usePathname();
  return (
    <SidebarGroup className="pt-1">
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton isActive={pathname === "/workspace/chats"} asChild>
            <Link className="text-muted-foreground" href="/workspace/chats">
              <MessagesSquare />
              <span>{t.sidebar.chats}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/agents")}
            asChild
          >
            <Link className="text-muted-foreground" href="/workspace/agents">
              <BotIcon />
              <span>{t.sidebar.agents}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/pipelines")}
            asChild
          >
            <Link className="text-muted-foreground" href="/workspace/pipelines">
              <CalendarClockIcon />
              <span>{t.sidebar.pipelines}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/approvals")}
            asChild
          >
            <Link className="text-muted-foreground" href="/workspace/approvals">
              <CheckCheckIcon />
              <span>{t.sidebar.approvals}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/vault")}
            asChild
          >
            <Link className="text-muted-foreground" href="/workspace/vault">
              <BookOpenIcon />
              <span>{t.sidebar.vault}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/integrations")}
            asChild
          >
            <Link className="text-muted-foreground" href="/workspace/integrations">
              <PlugZapIcon />
              <span>{t.sidebar.integrations}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/dreamy")}
            asChild
          >
            <Link className="text-muted-foreground" href="/workspace/dreamy/new">
              <SparklesIcon />
              <span>{t.sidebar.dreamy}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    </SidebarGroup>
  );
}
