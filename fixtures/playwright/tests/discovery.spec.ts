import { expect, test } from "@playwright/test";

test("discovers a typed Playwright test without launching a browser", async () => {
  expect(1 + 1).toBe(2);
});
