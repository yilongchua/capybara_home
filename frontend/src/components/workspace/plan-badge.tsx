"use client";

import { cn } from "@/lib/utils";

export function PlanBadge({
  className,
}: {
  className?: string;
}) {
  return (
    <div className="bg-blue-100 text-blue-600 px-3 py-1 rounded-full text-sm font-medium">
      Plan
    </div>
  );
}