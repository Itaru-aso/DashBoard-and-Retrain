import type { ReactNode } from "react";

import styles from "./StatusChip.module.css";

export type StatusVariant = "ok" | "warn" | "bad" | "neutral";

export interface StatusChipProps {
  variant: StatusVariant;
  children: ReactNode;
}

const VARIANT_CLASS: Record<StatusVariant, string> = {
  ok: styles.chipOk,
  warn: styles.chipWarn,
  bad: styles.chipBad,
  neutral: styles.chipNeutral,
};

export function StatusChip({ variant, children }: StatusChipProps) {
  return <span className={`${styles.chip} ${VARIANT_CLASS[variant]}`}>{children}</span>;
}
