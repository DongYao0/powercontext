/*
 * Copyright (c) 2026 OceanBase.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { answerConfirmation } from "./confirmation";
import { App } from "../src/app/App";
import { desktopApi } from "../src/shared/ipc";
import type { DesktopState } from "../src/generated/ipc";
vi.mock("../src/shared/ipc", () => ({
  getFoundationInfo: vi.fn().mockResolvedValue(null),
  desktopApi: {
    state: vi.fn(),
    check: vi.fn(),
    remember: vi.fn(),
    search: vi.fn(),
    scopes: vi.fn(),
    selectScope: vi.fn(),
    cancelMemory: vi.fn().mockResolvedValue(undefined),
    cancelScopes: vi.fn().mockResolvedValue(undefined),
  },
}));
const fact = { value: null, error: null };
const profile = {
  id: "a",
  name: "Original",
  revision: 1,
  endpoint: "http://127.0.0.1:8000",
  authentication: "unauthenticated_loopback" as const,
  caPem: null,
  compatibility: null,
  credentialState: "not_required" as const,
};
const report = {
  connectionId: "a",
  revision: 1,
  checkedAt: 1,
  liveness: fact,
  readiness: fact,
  identity: fact,
  capabilities: fact,
  compatibilityVerified: true,
  anonymousAccess: true,
  supportedOperations: [
    "remember_memory",
    "search_memory",
    "get_artifact_revision",
    "list_scopes",
    "get_scope",
  ],
};
const scope = {
  scope_id: "scope-a",
  title: "Scope A",
  summary: "",
  version: 1,
  context_references: [],
  external_references: [],
};
const state: DesktopState = {
  generation: 1,
  profiles: [profile],
  reports: [report],
  active: { connectionId: "a", generation: 1, report, scope },
  compatibilityProfiles: [],
  pendingCredentialCleanup: 0,
  lastWrite: null,
};
beforeEach(() => {
  vi.mocked(desktopApi.state).mockResolvedValue(state);
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

test.each(["使用此连接", "检查连接"])(
  "pending %s stays global after leaving the editor and prevents a draft in the stale context",
  async (action) => {
    const user = userEvent.setup();
    let finish!: (next: DesktopState) => void;
    vi.mocked(desktopApi.check).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "连接" }));
    await user.click(screen.getByRole("button", { name: /Original http/ }));
    await user.click(screen.getByRole("button", { name: action }));
    await user.click(screen.getByRole("button", { name: "记忆" }));
    expect(
      screen.getByRole("heading", { name: "正在更新连接状态…" }),
    ).toBeTruthy();
    const input = screen.getByRole("textbox", { name: "记忆内容" });
    expect(input.matches(":disabled")).toBe(true);
    await user.type(input, "this must not become a discarded draft");
    expect((input as HTMLTextAreaElement).value).toBe("");
    expect(
      screen.getByRole("button", { name: "保存" }).matches(":disabled"),
    ).toBe(true);
    expect(
      screen
        .getByRole("button", { name: /Scope A scope-a/ })
        .matches(":disabled"),
    ).toBe(true);
    expect(desktopApi.remember).not.toHaveBeenCalled();
    expect(desktopApi.search).not.toHaveBeenCalled();
    const next = {
      ...state,
      generation: 2,
      active: { ...state.active!, generation: 2, scope: null },
    };
    await act(async () => {
      finish(next);
    });
    expect(
      screen.queryByRole("heading", { name: "正在更新连接状态…" }),
    ).toBeNull();
    const selected = { ...scope, scope_id: "scope-b", title: "Scope B" };
    vi.mocked(desktopApi.scopes).mockResolvedValue({
      items: [selected],
      next_cursor: null,
    });
    vi.mocked(desktopApi.selectScope).mockResolvedValue({
      ...next,
      generation: 3,
      active: { ...next.active, generation: 3, scope: selected },
    });
    await user.click(screen.getByRole("button", { name: /未选择/ }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "查找范围" }));
    await user.click(within(dialog).getByRole("button", { name: "Scope B" }));
    const newInput = screen.getByRole("textbox", { name: "记忆内容" });
    await user.type(newInput, "new target draft");

    await user.click(screen.getByRole("button", { name: "观察" }));
    await answerConfirmation(user, false);
    expect((newInput as HTMLTextAreaElement).value).toBe("new target draft");
  },
  // This full navigation journey exceeds 5 seconds on shared Intel macOS runners.
  15_000,
);

test("a failed connection operation refreshes native state and releases the editing pause", async () => {
  const user = userEvent.setup();
  let fail!: (error: unknown) => void;
  vi.mocked(desktopApi.check).mockImplementationOnce(
    () =>
      new Promise((_, reject) => {
        fail = reject;
      }),
  );
  render(<App />);
  await user.click(await screen.findByRole("button", { name: "连接" }));
  await user.click(screen.getByRole("button", { name: /Original http/ }));
  await user.click(screen.getByRole("button", { name: "使用此连接" }));
  await user.click(screen.getByRole("button", { name: "记忆" }));
  expect(
    screen.getByRole("textbox", { name: "记忆内容" }).matches(":disabled"),
  ).toBe(true);
  // A busy rejection can precede any native context change.
  await act(async () => {
    fail({ code: "busy" });
  });
  const input = screen.getByRole("textbox", { name: "记忆内容" });
  expect(input.matches(":enabled")).toBe(true);
  expect(
    screen.queryByRole("heading", { name: "正在更新连接状态…" }),
  ).toBeNull();
  await user.type(input, "draft after failure");

  await user.click(screen.getByRole("button", { name: "观察" }));
  await answerConfirmation(user, false);
  expect((input as HTMLTextAreaElement).value).toBe("draft after failure");
});

test("a second rejected check cannot end the first pending connection operation", async () => {
  const user = userEvent.setup();
  let finish!: (next: DesktopState) => void;
  vi.mocked(desktopApi.check)
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    )
    .mockRejectedValueOnce({ code: "busy" });
  render(<App />);
  await user.click(await screen.findByRole("button", { name: "连接" }));
  await user.click(screen.getByRole("button", { name: /Original http/ }));
  await user.click(screen.getByRole("button", { name: "使用此连接" }));
  await user.click(screen.getByRole("button", { name: "观察" }));
  await user.click(screen.getByRole("button", { name: "连接" }));
  await user.click(screen.getByRole("button", { name: /Original http/ }));
  await user.click(screen.getByRole("button", { name: "使用此连接" }));
  await user.click(screen.getByRole("button", { name: "记忆" }));
  expect(
    screen.getByRole("textbox", { name: "记忆内容" }).matches(":disabled"),
  ).toBe(true);
  await act(async () => {
    finish({
      ...state,
      generation: 2,
      active: { ...state.active!, generation: 2, scope: null },
    });
  });
  expect(
    screen.queryByRole("heading", { name: "正在更新连接状态…" }),
  ).toBeNull();
});
