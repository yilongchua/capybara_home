import { useQueryClient } from "@tanstack/react-query";
import {
  BotIcon,
  Code2Icon,
  CopyIcon,
  DownloadIcon,
  EyeIcon,
  LoaderIcon,
  PackageIcon,
  PencilIcon,
  SaveIcon,
  SquareArrowOutUpRightIcon,
  Undo2Icon,
  XIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Streamdown } from "streamdown";

import {
  Artifact,
  ArtifactAction,
  ArtifactActions,
  ArtifactContent,
  ArtifactHeader,
  ArtifactTitle,
} from "@/components/ai-elements/artifact";
import { Select, SelectItem } from "@/components/ui/select";
import {
  SelectContent,
  SelectGroup,
  SelectTrigger,
} from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { CodeEditor } from "@/components/workspace/code-editor";
import { useArtifactContent } from "@/core/artifacts/hooks";
import { urlOfArtifact } from "@/core/artifacts/utils";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import { installSkill } from "@/core/skills/api";
import { streamdownSafePlugins } from "@/core/streamdown";
import { checkCodeFile, getFileName } from "@/core/utils/files";
import { env } from "@/env";
import { cn } from "@/lib/utils";

import { CitationLink } from "../citations/citation-link";
import { useThread } from "../messages/context";
import { Tooltip } from "../tooltip";

import { useDirectory } from "./context";
import { PlanViewer } from "./plan-viewer";

function truncateFilename(name: string): string {
  if (name.length <= 12) return name;
  return `${name.slice(0, 9)}...${name.slice(-5)}`;
}

export function ArtifactFileDetail({
  className,
  filepath: filepathFromProps,
  threadId,
  onClose,
  onSubmitPlanRevision,
}: {
  className?: string;
  filepath: string;
  threadId: string;
  onClose?: () => void;
  onSubmitPlanRevision?: (markdown: string) => Promise<void> | void;
}) {
  const { t } = useI18n();
  const { directoryFiles, deselect, select } = useDirectory();
  const isWriteFile = useMemo(() => {
    return filepathFromProps.startsWith("write-file:");
  }, [filepathFromProps]);
  const filepath = useMemo(() => {
    if (isWriteFile) {
      const url = new URL(filepathFromProps);
      return decodeURIComponent(url.pathname);
    }
    return filepathFromProps;
  }, [filepathFromProps, isWriteFile]);
  const isSkillFile = useMemo(() => {
    return filepath.endsWith(".skill");
  }, [filepath]);
  const isPlanFile = useMemo(() => {
    return (
      (filepath.endsWith("plan.md") &&
        (filepath.includes("/workspace/") || filepath.includes("/.handoff/") || filepath.includes("/.handoffs/"))) ||
      (filepath.includes("/workspace/plans/") && filepath.endsWith(".md") && filepath.includes("/plan-"))
    );
  }, [filepath]);
  const { isCodeFile, language } = useMemo(() => {
    if (isWriteFile) {
      let language = checkCodeFile(filepath).language;
      language ??= "text";
      return { isCodeFile: true, language };
    }
    // Treat .skill files as markdown (they contain SKILL.md)
    if (isSkillFile) {
      return { isCodeFile: true, language: "markdown" };
    }
    return checkCodeFile(filepath);
  }, [filepath, isWriteFile, isSkillFile]);
  const isSupportPreview = useMemo(() => {
    return language === "html" || language === "markdown";
  }, [language]);
  const { content } = useArtifactContent({
    threadId,
    filepath: filepathFromProps,
    enabled: !isWriteFile && (isCodeFile || isPlanFile),
  });

  const displayContent = content ?? "";
  const isPlanByFrontmatter = useMemo(() => {
    const trimmed = displayContent.trimStart();
    if (!trimmed.startsWith("---")) {
      return false;
    }
    return trimmed.includes("\nplan_version:");
  }, [displayContent]);
  const shouldRenderPlan = isPlanFile || isPlanByFrontmatter;

  const [viewMode, setViewMode] = useState<"code" | "preview">("code");
  const [isInstalling, setIsInstalling] = useState(false);
  const [planDraft, setPlanDraft] = useState("");
  const [isPlanEditing, setIsPlanEditing] = useState(false);
  const [isSavingPlan, setIsSavingPlan] = useState(false);
  const [isSubmittingPlanRevision, setIsSubmittingPlanRevision] = useState(false);
  const { isMock } = useThread();
  const queryClient = useQueryClient();
  useEffect(() => {
    if (isSupportPreview) {
      setViewMode("preview");
    } else {
      setViewMode("code");
    }
  }, [isSupportPreview]);

  useEffect(() => {
    if (shouldRenderPlan) {
      setPlanDraft(displayContent);
    } else {
      setPlanDraft("");
      setIsPlanEditing(false);
    }
  }, [displayContent, shouldRenderPlan]);

  const handleInstallSkill = useCallback(async () => {
    if (isInstalling) return;

    setIsInstalling(true);
    try {
      const result = await installSkill({
        thread_id: threadId,
        path: filepath,
      });
      if (result.success) {
        toast.success(result.message);
      } else {
        toast.error(result.message ?? "Failed to install skill");
      }
    } catch (error) {
      console.error("Failed to install skill:", error);
      toast.error("Failed to install skill");
    } finally {
      setIsInstalling(false);
    }
  }, [threadId, filepath, isInstalling]);

  const handleSavePlan = useCallback(async () => {
    if (isSavingPlan || !shouldRenderPlan) return;
    setIsSavingPlan(true);
    try {
      const response = await fetch(
        `${getBackendBaseURL()}/api/threads/${threadId}/artifacts/${filepath}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content: planDraft }),
        },
      );
      if (!response.ok) {
        throw new Error(await response.text());
      }
      await queryClient.invalidateQueries({
        queryKey: ["artifact", filepath, threadId, isMock],
        exact: false,
      });
      toast.success("Plan markdown saved.");
      setIsPlanEditing(false);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to save plan markdown.";
      toast.error(message);
    } finally {
      setIsSavingPlan(false);
    }
  }, [filepath, isMock, isSavingPlan, planDraft, queryClient, shouldRenderPlan, threadId]);

  const handleSubmitPlanRevision = useCallback(async () => {
    if (!onSubmitPlanRevision || isSubmittingPlanRevision || !shouldRenderPlan) return;
    setIsSubmittingPlanRevision(true);
    try {
      await onSubmitPlanRevision(planDraft);
      toast.success("Sent plan revision request.");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to submit plan revision request.";
      toast.error(message);
    } finally {
      setIsSubmittingPlanRevision(false);
    }
  }, [isSubmittingPlanRevision, onSubmitPlanRevision, planDraft, shouldRenderPlan]);

  const hasPlanChanges = shouldRenderPlan && planDraft !== displayContent;
  return (
    <Artifact className={cn(className)}>
      <ArtifactHeader className="px-2">
        <div className="flex items-center gap-2">
          <ArtifactTitle>
            {isWriteFile ? (
              <div className="px-2" title={getFileName(filepath)}>
                {truncateFilename(getFileName(filepath))}
              </div>
            ) : (
              <Select value={filepath} onValueChange={select}>
                <SelectTrigger
                  className="border-none bg-transparent! shadow-none select-none focus:outline-0 active:outline-0"
                  title={getFileName(filepath)}
                >
                  <span>{truncateFilename(getFileName(filepath))}</span>
                </SelectTrigger>
                <SelectContent className="select-none">
                  <SelectGroup>
                    {(directoryFiles ?? []).map((filepath) => (
                      <SelectItem key={filepath} value={filepath}>
                        {getFileName(filepath)}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            )}
          </ArtifactTitle>
        </div>
        <div className="flex min-w-0 grow items-center justify-center">
          {isSupportPreview && (
            <ToggleGroup
              className="mx-auto"
              type="single"
              variant="outline"
              size="sm"
              value={viewMode}
              onValueChange={(value) => {
                if (value) {
                  setViewMode(value as "code" | "preview");
                }
              }}
            >
              <ToggleGroupItem value="code">
                <Code2Icon />
              </ToggleGroupItem>
              <ToggleGroupItem value="preview">
                <EyeIcon />
              </ToggleGroupItem>
            </ToggleGroup>
          )}
        </div>
        <div className="flex items-center gap-2">
          <ArtifactActions>
            {!isWriteFile && filepath.endsWith(".skill") && (
              <Tooltip content={t.toolCalls.skillInstallTooltip}>
                <ArtifactAction
                  icon={isInstalling ? LoaderIcon : PackageIcon}
                  label={t.common.install}
                  tooltip={t.common.install}
                  disabled={
                    isInstalling ||
                    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"
                  }
                  onClick={handleInstallSkill}
                />
              </Tooltip>
            )}
            {shouldRenderPlan && (
              <>
                {!isPlanEditing ? (
                  <ArtifactAction
                    icon={PencilIcon}
                    label="Edit plan markdown"
                    tooltip="Edit plan markdown"
                    disabled={env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"}
                    onClick={() => setIsPlanEditing(true)}
                  />
                ) : (
                  <>
                    <ArtifactAction
                      icon={Undo2Icon}
                      label="Discard plan edits"
                      tooltip="Discard plan edits"
                      disabled={isSavingPlan}
                      onClick={() => {
                        setPlanDraft(displayContent);
                        setIsPlanEditing(false);
                      }}
                    />
                    <ArtifactAction
                      icon={isSavingPlan ? LoaderIcon : SaveIcon}
                      label="Save plan markdown"
                      tooltip="Save plan markdown"
                      disabled={isSavingPlan || !hasPlanChanges}
                      onClick={() => void handleSavePlan()}
                    />
                    <ArtifactAction
                      icon={isSubmittingPlanRevision ? LoaderIcon : BotIcon}
                      label="Apply edits to draft plan"
                      tooltip="Apply edits to draft plan"
                      disabled={
                        isSubmittingPlanRevision ||
                        isSavingPlan ||
                        !hasPlanChanges ||
                        !onSubmitPlanRevision
                      }
                      onClick={() => void handleSubmitPlanRevision()}
                    />
                  </>
                )}
              </>
            )}
            {!isWriteFile && (
              <a href={urlOfArtifact({ filepath, threadId })} target="_blank">
                <ArtifactAction
                  icon={SquareArrowOutUpRightIcon}
                  label={t.common.openInNewWindow}
                  tooltip={t.common.openInNewWindow}
                />
              </a>
            )}
            {isCodeFile && (
              <ArtifactAction
                icon={CopyIcon}
                label={t.clipboard.copyToClipboard}
                disabled={!content}
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(displayContent ?? "");
                    toast.success(t.clipboard.copiedToClipboard);
                  } catch (error) {
                    toast.error("Failed to copy to clipboard");
                    console.error(error);
                  }
                }}
                tooltip={t.clipboard.copyToClipboard}
              />
            )}
            {!isWriteFile && (
              <a
                href={urlOfArtifact({ filepath, threadId, download: true })}
                target="_blank"
              >
                <ArtifactAction
                  icon={DownloadIcon}
                  label={t.common.download}
                  tooltip={t.common.download}
                />
              </a>
            )}
            <ArtifactAction
              icon={XIcon}
              label={t.common.close}
              onClick={onClose ?? deselect}
              tooltip={t.common.close}
            />
          </ArtifactActions>
        </div>
      </ArtifactHeader>
      <ArtifactContent className="p-0">
        {shouldRenderPlan && displayContent && (
          <>
            {isPlanEditing ? (
              <div className="grid h-full min-h-0 grid-cols-2">
                <CodeEditor
                  className="h-full min-h-0 resize-none border-r"
                  value={planDraft}
                  onChange={setPlanDraft}
                />
                <div className="h-full min-h-0 overflow-auto border-l p-4">
                  <ArtifactFilePreview content={planDraft} language="markdown" />
                </div>
              </div>
            ) : (
              <PlanViewer content={displayContent} />
            )}
          </>
        )}
        {!shouldRenderPlan && isSupportPreview &&
          viewMode === "preview" &&
          (language === "markdown" || language === "html") && (
            <ArtifactFilePreview
              content={displayContent}
              language={language ?? "text"}
            />
          )}
        {!shouldRenderPlan && isCodeFile && viewMode === "code" && (
          <CodeEditor
            className="size-full resize-none rounded-none border-none"
            value={displayContent ?? ""}
            readonly
            wrapLines
          />
        )}
        {!shouldRenderPlan && !isCodeFile && (
          <iframe
            className="size-full"
            src={urlOfArtifact({ filepath, threadId, isMock })}
          />
        )}
      </ArtifactContent>
    </Artifact>
  );
}

export function ArtifactFilePreview({
  content,
  language,
}: {
  content: string;
  language: string;
}) {
  if (language === "markdown") {
    return (
      <div className="size-full px-4">
        <Streamdown
          className="size-full"
          {...streamdownSafePlugins}
          components={{ a: CitationLink }}
        >
          {content ?? ""}
        </Streamdown>
      </div>
    );
  }
  if (language === "html") {
    return (
      <iframe
        className="size-full"
        title="Artifact preview"
        srcDoc={content}
        sandbox="allow-scripts allow-forms"
      />
    );
  }
  return null;
}
