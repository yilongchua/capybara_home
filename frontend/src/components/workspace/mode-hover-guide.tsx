"use client";

import * as React from "react";

export type AgentMode = "work" | "plan";

function getModeLabel(mode: AgentMode): string {
  switch (mode) {
    case "work":
      return "Work Mode";
    case "plan":
      return "Plan Mode";
  }
}

function getModeDescription(mode: AgentMode): string {
  switch (mode) {
    case "work":
      return "Direct execution. Simple requests run immediately; complex tasks create a plan and execute phases automatically.";
    case "plan":
      return "Deep planning mode. Generates a structured execution plan with editable phases before running.";
  }
}

export function ModeHoverGuide({
  mode,
  children,
  showTitle = true,
}: {
  mode: AgentMode;
  children: React.ReactNode;
  showTitle?: boolean;
}) {
  const label = getModeLabel(mode);
  const description = getModeDescription(mode);
  const content = showTitle ? `${label}: ${description}` : description;

  if (React.isValidElement<{ title?: string }>(children)) {
    const childProps = children.props ?? {};
    return React.cloneElement(children, {
      title: childProps.title ?? content,
    });
  }

  return <span title={content}>{children}</span>;
}
