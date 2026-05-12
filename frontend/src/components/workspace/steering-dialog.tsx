"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useI18n } from "@/core/i18n/hooks";

interface SteeringDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  isPending: boolean;
}

export function SteeringDialog({
  open,
  onOpenChange,
  value,
  onChange,
  onSubmit,
  isPending,
}: SteeringDialogProps) {
  const { t } = useI18n();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t.steering.title}</DialogTitle>
          <DialogDescription>{t.steering.description}</DialogDescription>
        </DialogHeader>
        <Input
          autoFocus
          placeholder={t.steering.inputPlaceholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              onSubmit();
            }
          }}
        />
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            {t.common.cancel}
          </Button>
          <Button type="button" onClick={onSubmit} disabled={isPending}>
            {isPending ? t.steering.applying : t.steering.apply}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
