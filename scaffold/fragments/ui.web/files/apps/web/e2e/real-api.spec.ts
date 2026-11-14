import { expect, test } from "@playwright/test";

// Opt-in: `E2E_REAL_API=1 E2E_USERNAME=... E2E_PASSWORD=... pnpm test:e2e:real`
// The mocked chat/governance specs remain the default `pnpm test:e2e` path.
test.skip(
  process.env.E2E_REAL_API !== "1",
  "set E2E_REAL_API=1 with E2E_USERNAME/E2E_PASSWORD to run against a live API",
);

test("real API: sign in, chat, feedback and learning dashboard", async ({
  page,
}) => {
  const username = process.env.E2E_USERNAME;
  const password = process.env.E2E_PASSWORD;
  test.skip(!username || !password, "E2E_USERNAME and E2E_PASSWORD are required");

  await page.goto("/");
  await page.getByLabel("Username").fill(username!);
  await page.getByLabel("Password").fill(password!);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();

  await expect(page.getByRole("heading", { name: "Ask anything" })).toBeVisible({
    timeout: 15_000,
  });

  await page.getByLabel("Ask a question…").fill("hello");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByText("hello", { exact: true })).toBeVisible();

  const helpful = page.getByRole("button", { name: "Helpful", exact: true });
  await expect(helpful).toBeVisible({ timeout: 30_000 });
  await helpful.click();
  await expect(page.getByText("Thanks for the feedback.")).toBeVisible();

  await page.goto("/learning");
  await expect(page.getByRole("heading", { name: "Agent learning" })).toBeVisible();
  await expect(page.getByText("Pass rate")).toBeVisible();
  await expect(page.getByLabel("Staged rollout")).toBeVisible();
});
