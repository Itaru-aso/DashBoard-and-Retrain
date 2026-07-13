import { Outlet } from "react-router-dom";

import Header from "@/components/Header";
import Sidebar from "@/components/Sidebar";

import styles from "./AppLayout.module.css";

/** 全画面共通のレイアウト（ヘッダー＋サイドバー＋子ルート）。 */
export default function AppLayout() {
  return (
    <div className={styles.shell}>
      <Header />
      <div className={styles.body}>
        <Sidebar />
        <main className={styles.main}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
