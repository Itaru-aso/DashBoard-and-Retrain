import axios, { AxiosError } from "axios";

// API クライアント。開発は Vite が /api をバックエンドへプロキシし、
// 本番は FastAPI が同一オリジンで配信する（いずれも baseURL は /api）。
export const apiClient = axios.create({
  baseURL: "/api",
});

// バックエンドの検証・業務エラーは JSON の `detail` に理由を載せる（FastAPI 既定）。
// 画面が (error as Error).message で理由を出せるよう、error.message を detail に差し替える。
apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError<{ detail?: unknown }>) => {
    const detail = error.response?.data?.detail;
    if (detail != null) {
      error.message = typeof detail === "string" ? detail : JSON.stringify(detail);
    }
    return Promise.reject(error);
  },
);
