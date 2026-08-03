import type { ReactNode } from "react";

import { StatusChip, type StatusVariant } from "./StatusChip";
import styles from "./StatTile.module.css";

export interface StatTileProps {
  label: string;
  value: string;
  status?: StatusVariant;
  statusLabel?: string;
  caption?: string;
  sparkline?: ReactNode;
}

export function StatTile({ label, value, status, statusLabel, caption, sparkline }: StatTileProps) {
  return (
    <div className={styles.tile}>
      <div className={styles.head}>
        <span className={styles.label}>{label}</span>
        {status && statusLabel && <StatusChip variant={status}>{statusLabel}</StatusChip>}
      </div>
      <div className={styles.value}>{value}</div>
      {caption && <div className={styles.caption}>{caption}</div>}
      {sparkline && <div className={styles.sparkline}>{sparkline}</div>}
    </div>
  );
}
