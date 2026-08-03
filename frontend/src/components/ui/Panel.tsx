import type { ReactNode } from "react";

import styles from "./Panel.module.css";

export interface PanelProps {
  title?: string;
  actions?: ReactNode;
  children: ReactNode;
}

export function Panel({ title, actions, children }: PanelProps) {
  const hasHeader = Boolean(title) || Boolean(actions);

  return (
    <section className={styles.panel}>
      {hasHeader && (
        <div className={styles.header}>
          {title && <h2 className={styles.title}>{title}</h2>}
          {actions && <div className={styles.actions}>{actions}</div>}
        </div>
      )}
      <div className={styles.body}>{children}</div>
    </section>
  );
}
