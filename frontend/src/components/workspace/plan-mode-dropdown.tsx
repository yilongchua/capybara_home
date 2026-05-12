"use client";

export function PlanModeDropdown({
  planModeActive,
  onTogglePlanMode,
  triggerId,
}: {
  planModeActive: boolean;
  onTogglePlanMode: () => void;
  triggerId: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <div className="flex items-center gap-2">
        <span className="text-xs text-blue-400">Plan</span>
        <div className="w-8 h-5 bg-gray-200 rounded-full relative cursor-pointer">
          <div
            className="absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-blue-400 transition-transform"
            style={{ transform: "translateX(0)" }}
          />
        </div>
      </div>
    </div>
  );
}
