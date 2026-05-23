"use client";

import { cn } from "@/lib/utils";

export function Welcome({
  className,
  mode: _mode,
}: {
  className?: string;
  mode?: "work" | "plan";
}) {
  return (
    <div
      className={cn(
        "mx-auto flex w-full flex-col items-center justify-center gap-2 px-8 py-4 text-center",
        className,
      )}
    >
      <div className="text-2xl font-bold">
        <div className="flex items-center gap-2">
          <img src="/Logo.webp" alt="CapyHome logo" className="size-8" />
          <span>Welcome to CapyHome!</span>
        </div>
      </div>
      <div className="text-muted-foreground text-sm">
        <p>
          Think less, create more. CapyHome handles the hard stuff while you
          focus on what matters 🚀
        </p>
      </div>

    </div>
  );
}
