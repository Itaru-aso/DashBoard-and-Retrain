// 配置先: frontend/src/App.tsx（または既存ルーター定義箇所）への追記例。
// 再学習画面を React Router に登録する。既存のルーター構成に合わせて取り込むこと。

import { lazy, Suspense } from "react";
import { createBrowserRouter, RouterProvider, NavLink, Outlet } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// コード分割（任意）。同期 import でも可。
const Retraining = lazy(() => import("./pages/Retraining"));
// const Dashboard = lazy(() => import("./pages/Dashboard"));
// const Tasks = lazy(() => import("./pages/Tasks"));
// const ColorMaster = lazy(() => import("./pages/ColorMaster"));

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false } },
});

function AppLayout() {
  return (
    <div className="app-shell">
      <nav className="app-nav" aria-label="メイン">
        {/* 既存ナビに合わせて並べる */}
        {/* <NavLink to="/">ダッシュボード</NavLink> */}
        <NavLink to="/retraining">モデル再学習</NavLink>
        {/* <NavLink to="/tasks">保守タスク</NavLink>
        <NavLink to="/colors">色マスター</NavLink> */}
      </nav>
      <Suspense fallback={<div className="loading">読み込み中…</div>}>
        <Outlet />
      </Suspense>
    </div>
  );
}

const router = createBrowserRouter([
  {
    path: "/",
    element: <AppLayout />,
    children: [
      // { index: true, element: <Dashboard /> },
      { path: "retraining", element: <Retraining /> },
      // { path: "tasks", element: <Tasks /> },
      // { path: "colors", element: <ColorMaster /> },
    ],
  },
]);

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
