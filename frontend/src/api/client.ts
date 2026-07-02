import axios from "axios";

// API クライアント。開発は Vite が /api をバックエンドへプロキシし、
// 本番は FastAPI が同一オリジンで配信する（いずれも baseURL は /api）。
export const apiClient = axios.create({
  baseURL: "/api",
});
