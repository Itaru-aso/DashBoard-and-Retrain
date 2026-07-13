import { useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

import styles from "./Sidebar.module.css";

const SETTINGS_PATHS = ["/colors", "/thresholds", "/edge-pcs"];

function navItemClassName({ isActive }: { isActive: boolean }): string {
  return isActive ? `${styles.navItem} ${styles.navItemActive}` : styles.navItem;
}

function subNavItemClassName({ isActive }: { isActive: boolean }): string {
  return isActive ? `${styles.subNavItem} ${styles.subNavItemActive}` : styles.subNavItem;
}

/** 全画面共通のサイドバーナビゲーション（3項目＋「設定」開閉で3項目）。 */
export default function Sidebar() {
  const location = useLocation();
  const [settingsOpen, setSettingsOpen] = useState(() =>
    SETTINGS_PATHS.includes(location.pathname),
  );

  return (
    <aside className={styles.sidebar}>
      <div className={styles.sectionLabel}>メニュー</div>

      <NavLink to="/dashboard" end className={navItemClassName}>
        <span className={styles.navItemIcon}>
          <svg width="15" height="15" viewBox="0 0 16 16" fill="currentColor">
            <rect x="1" y="1" width="6" height="6" rx="1.5" />
            <rect x="9" y="1" width="6" height="6" rx="1.5" />
            <rect x="1" y="9" width="6" height="6" rx="1.5" />
            <rect x="9" y="9" width="6" height="6" rx="1.5" />
          </svg>
        </span>
        ダッシュボード
      </NavLink>

      <NavLink to="/retraining" end className={navItemClassName}>
        <span className={styles.navItemIcon}>
          <svg
            width="15"
            height="15"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.4"
          >
            <circle cx="8" cy="8" r="3" />
          </svg>
        </span>
        AI学習
      </NavLink>

      <NavLink to="/tasks" end className={navItemClassName}>
        <span className={styles.navItemIcon}>
          <svg
            width="15"
            height="15"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.4"
          >
            <rect x="2" y="2" width="12" height="12" rx="2.5" />
            <path d="M5 8l2 2 4-4.5" />
          </svg>
        </span>
        タスク
      </NavLink>

      <button
        type="button"
        className={styles.settingsToggle}
        onClick={() => setSettingsOpen((open) => !open)}
        aria-expanded={settingsOpen}
      >
        <span className={styles.navItemIcon}>
          <svg
            width="15"
            height="15"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.4"
          >
            <line x1="2" y1="5" x2="14" y2="5" />
            <line x1="2" y1="11" x2="14" y2="11" />
          </svg>
        </span>
        設定
      </button>

      {settingsOpen && (
        <div className={styles.settingsSubmenu}>
          <NavLink to="/colors" end className={subNavItemClassName}>
            色マスター
          </NavLink>
          <NavLink to="/thresholds" end className={subNavItemClassName}>
            閾値
          </NavLink>
          <NavLink to="/edge-pcs" end className={subNavItemClassName}>
            エッジPC
          </NavLink>
        </div>
      )}

      <div className={styles.spacer} />
    </aside>
  );
}
