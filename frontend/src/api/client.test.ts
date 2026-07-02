import { describe, expect, it } from "vitest";

import { apiClient } from "./client";

describe("apiClient", () => {
  it("baseURL が /api に設定されている", () => {
    expect(apiClient.defaults.baseURL).toBe("/api");
  });
});
