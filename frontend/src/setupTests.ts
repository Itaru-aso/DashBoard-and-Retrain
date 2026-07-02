// Vitest 実行時に jest-dom のマッチャ（toBeInTheDocument 等）を登録する。
import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// globals:false のため Testing Library の自動 cleanup が効かない。明示的に各テスト後に
// DOM を掃除し、レンダリングがテスト間で累積しないようにする。
afterEach(() => {
  cleanup();
});
