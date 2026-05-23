"use client";

import { MessageSquarePlus } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";

import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";
import { useLocalSettings } from "@/core/settings";
import { env } from "@/env";
import { cn } from "@/lib/utils";

const DEFAULT_ICON = {
  src: "/Logo.webp",
  width: 32,
  height: 32,
  alt: "CapyHome",
};

const PLAN_MODE_ICON = {
  src: "/plan-mode-icon.webp",
  width: 297,
  height: 223,
  alt: "Plan mode",
};

const WORK_MODE_ICON = {
  src: "/work-mode-icon.webp",
  width: 342,
  height: 204,
  alt: "Work mode",
};

export function WorkspaceHeader({ className }: { className?: string }) {
  const { t } = useI18n();
  const { state } = useSidebar();
  const pathname = usePathname();
  const [settings] = useLocalSettings();

  const isNewChat = pathname === "/workspace/chats/new";
  const navIcon = isNewChat
    ? settings.context.mode === "plan"
      ? PLAN_MODE_ICON
      : WORK_MODE_ICON
    : DEFAULT_ICON;
  return (
    <>
      <div
        className={cn(
          "group/workspace-header flex flex-col",
          isNewChat && "border-border border-b-2",
          (state === "collapsed" || !isNewChat) && "h-12 justify-center",
          className,
        )}
      >
        {state === "collapsed" ? (
          <div className="group-has-data-[collapsible=icon]/sidebar-wrapper:-translate-y flex w-full cursor-pointer items-center justify-center">
            <div className="block group-hover/workspace-header:hidden">
              <Image
                src={navIcon.src}
                alt={navIcon.alt}
                width={navIcon.width}
                height={navIcon.height}
                className="h-6 w-auto object-contain"
                priority
              />
            </div>
            <SidebarTrigger className="hidden pl-2 group-hover/workspace-header:block" />
          </div>
        ) : isNewChat ? (
          <div className="relative">
            {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ? (
              <Link href="/" className="block">
                <Image
                  src={navIcon.src}
                  alt={navIcon.alt}
                  width={navIcon.width}
                  height={navIcon.height}
                  className="block h-auto w-full object-cover"
                  priority
                />
              </Link>
            ) : (
              <Image
                src={navIcon.src}
                alt={navIcon.alt}
                width={navIcon.width}
                height={navIcon.height}
                className="block h-auto w-full object-cover"
                priority
              />
            )}
            <SidebarTrigger className="bg-background/70 hover:bg-background absolute top-1.5 right-1.5 backdrop-blur-sm" />
          </div>
        ) : (
          <div className="flex items-center justify-between gap-2">
            {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ? (
              <Link href="/" className="ml-2 flex items-center gap-2">
                <Image
                  src={navIcon.src}
                  alt={navIcon.alt}
                  width={navIcon.width}
                  height={navIcon.height}
                  className="h-8 w-auto object-contain"
                  priority
                />
                <span className="text-primary font-sans text-base font-bold tracking-tight">
                  CapyHome
                </span>
              </Link>
            ) : (
              <div className="ml-2 flex cursor-default items-center gap-2">
                <Image
                  src={navIcon.src}
                  alt={navIcon.alt}
                  width={navIcon.width}
                  height={navIcon.height}
                  className="h-8 w-auto object-contain"
                  priority
                />
                <span className="text-primary font-sans text-base font-bold tracking-tight">
                  CapyHome
                </span>
              </div>
            )}
            <SidebarTrigger />
          </div>
        )}
      </div>
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname === "/workspace/chats/new"}
            asChild
          >
            <Link className="text-muted-foreground" href="/workspace/chats/new">
              <MessageSquarePlus size={16} />
              <span>{t.sidebar.newChat}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    </>
  );
}
