import styles from "./Header.module.css";

/** 全画面共通のヘッダー（ロゴ・アプリ名・エッジPC稼働の静的プレースホルダー）。 */
export default function Header() {
  return (
    <header className={styles.header}>
      <div className={styles.logo}>
        <div className={styles.logoIcon}>
          <span />
        </div>
        <div className={styles.titles}>
          <span className={styles.appName}>Shisui</span>
          <span className={styles.subtitle}>外観検査モニタリング</span>
        </div>
      </div>

      <div className={styles.spacer} />

      <div className={styles.edgeStatus}>
        <span className={styles.edgeStatusDot} />
        エッジPC <span className={styles.edgeStatusValue}>―/―</span> 稼働
      </div>
      <div className={styles.lanBadge}>オンプレ LAN</div>
    </header>
  );
}
