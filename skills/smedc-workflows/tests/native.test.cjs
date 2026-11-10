const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const filename = path.join(__dirname, "../scripts/native-adapters.js");
const factory = () => {
  const create = vm.runInNewContext(fs.readFileSync(filename, "utf8"), {
    setTimeout,
    clearTimeout,
  });
  return (tools, options = {}) =>
    create(tools, {
      officialBinding: {
        entryName: "smedc",
        namespace: "mcp__smedc__",
        serviceOrigin: "https://api.smedatacenter.xyz",
      },
      ...options,
    });
};
const hostTask = {
  id: "task-new",
  kind: "cron",
  projectId: "project-new",
  executionEnvironment: "local",
  status: "PAUSED",
  rrule: "FREQ=DAILY;BYHOUR=3;BYMINUTE=45",
  model: "gpt-6.1-sol",
  reasoningEffort: "high",
  notificationPolicy: "failed_runs_only",
  prompt: "Use installed workflow",
};
test("install reads native host schedule and repeats without a duplicate task", async () => {
  let creates = 0;
  const journal = {};
  const tools = {
    mcp__codex_app__list_projects: async () => ({
      projects: [{ id: "project-new", type: "local" }],
    }),
    mcp__codex_app__automation_update: async (input) => {
      if (input.mode === "create") creates++;
      return {
        content: [
          { type: "text", text: "Created automation in the app." },
          {
            type: "text",
            text: JSON.stringify({
              automationId: "task-new",
              mode: input.mode,
              status: "PAUSED",
            }),
          },
        ],
      };
    },
    exec_command: async () => ({
      exit_code: 0,
      output: JSON.stringify(hostTask),
    }),
  };
  const native = factory()(tools, { localScript: "/isolated/workflow.py" });
  const input = {
    workflowId: "flow",
    projectId: "project-new",
    prompt: "Use installed workflow",
    name: "Example",
    rrule: hostTask.rrule,
    model: hostTask.model,
    reasoningEffort: "high",
    timezone: "Asia/Shanghai",
    platform: "macos",
  };
  await native.install(input, journal, async () => {});
  await native.install(input, journal, async () => {});
  assert.equal(creates, 1);
  assert.equal(journal.hostSnapshot.state, "paused");
});
test("lost host create response is not retried on a repeated install", async () => {
  let creates = 0;
  const journal = {};
  const native = factory()({
    mcp__codex_app__list_projects: async () => ({ projects: [{ id: "p" }] }),
    mcp__codex_app__automation_update: async () => {
      creates++;
      throw new Error("timeout");
    },
  });
  const input = {
    workflowId: "w",
    projectId: "p",
    platform: "macos",
    timezone: "Asia/Shanghai",
    model: "gpt-6.1-sol",
    reasoningEffort: "high",
    name: "Synthetic",
    prompt: "Use installed workflow",
    rrule: "FREQ=DAILY;BYHOUR=3;BYMINUTE=45",
  };
  await assert.rejects(native.install(input, journal, async () => {}));
  await assert.rejects(
    native.install(input, journal, async () => {}),
    /unknown/,
  );
  assert.equal(creates, 1);
});
test("revoked live control blocks a native Gmail send", async () => {
  let sends = 0;
  const native = factory()({
    mcp__codex_apps__gmail_get_profile: async () => ({
      emailAddress: "sender@example.test",
    }),
    mcp__smedc__manage_workflow_run: async () => {
      throw new Error("revoked");
    },
    mcp__codex_apps__gmail_send_email: async () => {
      sends++;
    },
  });
  await assert.rejects(
    native.sendEmail(
      {
        workflowId: "w",
        installationId: "i",
        runId: "r",
        assignmentEpoch: 1,
        controlVersion: 1,
      },
      {
        actionId: "a",
        identity: {
          kind: "email",
          sender: "sender@example.test",
          recipients: ["receiver@example.test"],
        },
        artifactHash: "hash",
        correlationMarker: "marker",
      },
      {
        artifactHash: "hash",
        payload: { mime_type: "text/html", body: { content: "Final" } },
      },
    ),
    /revoked/,
  );
  assert.equal(sends, 0);
});
test("readback confirms the exact sent artifact without a manual-resolution bypass", async () => {
  const crypto = require("node:crypto");
  const content = "<html>Final report</html>";
  const hash = crypto.createHash("sha256").update(content).digest("hex");
  let receipt, refreshed = false, claims = 0;
  const installation = {
    ...readyInstallation(), installationId: "i",
    readinessChecks: ["email_identity", "sent_mail_lookup"].map((capability) => ({
      capability, status: "ready", checkedAt: "2026-11-01T00:00:00Z",
    })),
  };
  const intent = {
    actionId: "a",
    identity: {
      kind: "email",
      purpose: "review_drafts",
      sender: "sender@example.test",
      recipients: ["receiver@example.test"],
    },
    artifactHash: hash,
    correlationMarker: "marker",
  };
  const native = factory()(
    {
      mcp__codex_apps__gmail_get_profile: async () => ({
        emailAddress: "sender@example.test",
      }),
      mcp__smedc__get_workflow_status: async () => ({
        workflowId: "w", workflowType: "meituan-review-operations",
        assignedInstallationId: "i", controlState: "active",
        observedAt: new Date().toISOString(), installations: [installation],
      }),
      mcp__codex_apps__gmail_search_email_ids: async (request) => {
        assert.equal(request.query, "in:sent");
        return { message_ids: [] };
      },
      mcp__smedc__manage_workflow_installation: async ({ operation }) => {
        assert.equal(operation.kind, "record_checks");
        assert.equal(operation.firstRunVerification, "verified");
        assert.equal(operation.checks.length, 2);
        assert.ok(operation.checks.every((check) => check.status === "ready" &&
          Date.parse(check.checkedAt) > Date.now() - 60000));
        refreshed = true;
        return { ...installation, readinessChecks: operation.checks };
      },
      mcp__smedc__manage_workflow_run: async () => ({ ok: true }),
      mcp__smedc__record_workflow_action: async (input) => {
        if (input.operation.kind === "intent" && ++claims === 1)
          return { error: { code: "WORKFLOW_SOURCE_UNAVAILABLE" } };
        if (input.operation.kind === "intent")
          return {
            actions: [
              {
                actionId: "a",
                state: "intent",
                permitted: true,
                identityHash: "identity-hash",
              },
            ],
          };
        receipt = input.operation.receipts[0];
        return { recorded: 1, receipts: [receipt] };
      },
      mcp__codex_apps__gmail_send_email: async () => {
        assert.equal(refreshed, true);
        assert.equal(claims, 2);
        return { id: "provider-id" };
      },
      mcp__codex_apps__gmail_read_email_thread: async () => ({
        messages: [
          {
            id: "provider-id",
            label_ids: ["SENT"],
            payload: {
              headers: [
                { name: "From", value: "sender@example.test" },
                { name: "To", value: "receiver@example.test" },
                { name: "Subject", value: "Weekly [marker]" },
              ],
              mime_type: "text/html",
              body: { content },
            },
          },
        ],
      }),
    },
    { saveOutcome: async () => {} },
  );
  const result = await native.sendEmail(
    {
      workflowId: "w",
      installationId: "i",
      runId: "r",
      assignmentEpoch: 1,
      controlVersion: 1,
    },
    intent,
    {
      artifactHash: hash,
      subject: "Weekly",
      payload: { mime_type: "text/html", body: { content } },
    },
  );
  assert.equal(result.state, "confirmed");
  assert.equal(receipt.evidence, "provider_readback");
  assert.equal(receipt.providerReadback.providerReceiptId, "provider-id");
});
test("long native operation renews its lease and retains uncertain outcome after renewal failure", async () => {
  let timer;
  let renews = 0;
  let finish;
  const durable = [];
  const clock = {
    setTimeout: (fn) => {
      timer = fn;
      return 1;
    },
    clearTimeout: () => {
      timer = undefined;
    },
  };
  const native = factory()(
    {
      mcp__smedc__manage_workflow_run: async () => {
        renews++;
        if (renews === 2) throw new Error("revoked");
        return {};
      },
    },
    { timers: clock },
  );
  const session = {
    workflowId: "w",
    installationId: "i",
    runId: "r",
    assignmentEpoch: 1,
    controlVersion: 1,
    renewAfterSeconds: 30,
  };
  const operation = native.withLease(
    session,
    { stage: "download", effect: "external_write" },
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
    async (event) => durable.push(event),
  );
  await new Promise((resolve) => setImmediate(resolve));
  timer();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(renews, 1);
  timer();
  await new Promise((resolve) => setImmediate(resolve));
  finish({ jobId: "original-job" });
  await assert.rejects(operation, /lease/i);
  assert.equal(durable.at(-1).state, "unknown");
  assert.equal(durable.at(-1).result.jobId, "original-job");
  await assert.rejects(native.check(session, { actionId: "next" }), /lease/i);
});
test("host activation is refused when the central assignment belongs to another installation", async () => {
  let updates = 0;
  const native = factory()({
    mcp__smedc__get_enterprise_workflow: async () => ({
      workflowId: "w",
      controlState: "active",
      assignedInstallationId: "another",
      capability: {
        id: "enterprise-workflows-v1",
        version: "1.0.0",
        configurationSchemaVersion: 1,
        minimumLauncherVersion: "0.16.0",
      },
    }),
    mcp__codex_app__automation_update: async () => {
      updates++;
    },
  });
  await assert.rejects(
    native.setHostState(
      {
        workflowId: "w",
        enterpriseKey: "demo",
        workflowType: "weekly-business-report",
        installationId: "mine",
        handoff: {
          kind: "legacy_paused",
          acknowledged: true,
          proofHash: "a".repeat(64),
          confirmedAt: "2026-11-02T00:00:00Z",
        },
      },
      { workflowId: "w", taskId: "task", hostSnapshot: {} },
      "enabled",
      async () => {},
    ),
    /assignment/i,
  );
  assert.equal(updates, 0);
});
test("an unknown send is reconciled after a fresh task context without sending again", async () => {
  const crypto = require("node:crypto");
  const content = "<p>New draft 😀</p>";
  const hash = crypto.createHash("sha256").update(content).digest("hex");
  let sends = 0,
    state = "intent",
    resolution;
  const identity = {
    kind: "email",
    purpose: "review_drafts",
    sender: "sender@example.test",
    recipients: ["owner@example.test"],
  };
  const intent = {
    actionId: "old-action",
    identity,
    artifactHash: hash,
    correlationMarker: "stable-marker",
  };
  const tools = {
    mcp__smedc__manage_workflow_run: async () => ({}),
    mcp__smedc__record_workflow_action: async ({ operation }) => {
      if (operation.kind === "intent")
        return {
          actions: [
            {
              actionId: intent.actionId,
              state,
              permitted: state === "intent",
              identityHash: "a".repeat(64),
            },
          ],
        };
      if (operation.kind === "get")
        return {
          actions: [{ ...intent, state, identityHash: "a".repeat(64) }],
        };
      if (operation.kind === "resolve_unknown") {
        resolution = operation.receipt;
        return { recorded: 1 };
      }
      state = operation.receipts[0].state;
      return { recorded: 1 };
    },
    mcp__codex_apps__gmail_get_profile: async () => ({
      emailAddress: "sender@example.test",
    }),
    mcp__codex_apps__gmail_send_email: async () => {
      sends++;
      throw new Error("Response lost after provider dispatch");
    },
    mcp__codex_apps__gmail_search_email_ids: async () => ({
      messages: [{ id: "original-provider-id" }],
    }),
    mcp__codex_apps__gmail_read_email_thread: async () => ({
      messages: [
        {
          id: "original-provider-id",
          label_ids: ["SENT"],
          subject: "Drafts [stable-marker]",
          from: "sender@example.test",
          to: "owner@example.test",
          payload: { body: { content } },
        },
      ],
    }),
  };
  const session = {
    workflowId: "w",
    installationId: "replacement-installation",
    runId: "replacement-run",
    assignmentEpoch: 2,
    controlVersion: 2,
  };
  const native = factory()(tools, { saveOutcome: async () => {} });
  assert.equal(
    (
      await native.sendEmail(session, intent, {
        artifactHash: hash,
        subject: "Drafts",
        payload: { body: { content } },
      })
    ).state,
    "unknown",
  );
  assert.equal(
    (
      await native.sendEmail(session, intent, {
        artifactHash: hash,
        subject: "Drafts",
        payload: { body: { content } },
      })
    ).reconcile,
    true,
  );
  assert.equal(
    (
      await factory()(tools).reconcileEmail(session, intent, {
        identityHash: "a".repeat(64),
      })
    ).state,
    "confirmed",
  );
  assert.equal(sends, 1);
  assert.equal(resolution.receiptId, "original-provider-id");
});
test("a fresh machine discovers all migration pages and restores original unknown metadata without old local state", async () => {
  const crypto = require("node:crypto");
  const hash = (value) =>
    crypto.createHash("sha256").update(JSON.stringify(value)).digest("hex");
  const chunks = [
    [
      {
        completedActions: [],
        recoveryItems: [
          {
            disposition: "open",
            itemId: "unfinished",
            kind: "business",
            scope: {
              kind: "report",
              storeNames: ["Demo"],
              window: { endDate: "2025-10-26", startDate: "2025-10-20" },
            },
            stage: "delivering",
          },
        ],
        unresolved: [],
        workflowId: "weekly",
      },
    ],
    [
      {
        completedActions: [],
        recoveryItems: [
          {
            disposition: "waived",
            itemId: "waived-evidence",
            kind: "evidence",
            resolutionReason: "Explicit legacy waiver",
            scope: { kind: "unknown_scope", reason: "missing_local_evidence" },
            stage: "finished",
          },
        ],
        unresolved: [],
        workflowId: "weekly",
      },
    ],
  ];
  // Literal objects are in canonical key order; independent crypto computes the expected chain.
  const chunkHashes = chunks.map(hash);
  let chain = "0".repeat(64);
  chunks.forEach((_, i) => (chain = hash([chain, i, chunkHashes[i], 1])));
  const summary = {
    migrationId: "discovered-migration",
    workflowIds: ["daily", "reviews", "weekly"],
    stage: "imported",
    sourceSnapshotHash: "a".repeat(64),
    recordCount: 2,
    chunkCount: 2,
    chunksDigest: chain,
    targetVersion: 1,
    createdAt: "2026-10-01T00:00:00Z",
  };
  const archived = [];
  let created = 0;
  const current = {
    workflowId: "weekly",
    enterpriseKey: "demo-enterprise",
    workflowType: "weekly-business-report",
    version: 7,
    integration: { version: 4 },
    controlVersion: 3,
    assignmentEpoch: 2,
    assignedInstallationId: "old-managed",
    configuration: { delivery: { recipients: ["new-owner@example.test"] } },
    capability: {
      id: "enterprise-workflows-v1",
      version: "1.0.0",
      configurationSchemaVersion: 1,
      minimumLauncherVersion: "0.16.0",
    },
  };
  const tools = {
    mcp__smedc__get_enterprise_workflow: async () => current,
    mcp__smedc__get_workflow_status: async () => ({
      ...current,
      pendingActions: [
        { actionId: "unknown-mail", runId: "old-run", state: "unknown" },
      ],
      nextActionCursor: null,
      migrations: [summary],
      nextMigrationCursor: null,
      installations: [
        {
          installationId: "old-managed",
          hostSnapshot: {
            cron: "current-confirmed-schedule",
            model: "gpt-6.1-sol",
            state: "paused",
          },
        },
      ],
    }),
    mcp__smedc__record_workflow_action: async () => ({
      actions: [
        {
          actionId: "unknown-mail",
          state: "unknown",
          identity: { kind: "email" },
          identityHash: "b".repeat(64),
          artifactHash: "c".repeat(64),
          correlationMarker: "original-provider-marker",
        },
      ],
    }),
    mcp__smedc__manage_workflow_installation: async ({ operation }) => {
      const i = operation.cursor ?? 0;
      return {
        ...summary,
        manifest: {
          workflows: [
            {
              workflowId: "weekly",
              configuration: {
                delivery: { recipients: ["obsolete-owner@example.test"] },
              },
              hostSnapshot: { cron: "historical-schedule" },
            },
          ],
        },
        chunks: [{ sequence: i, chunk: chunks[i], chunkHash: chunkHashes[i] }],
        nextCursor: i === 0 ? 1 : null,
      };
    },
    mcp__codex_app__automation_update: async () => {
      created++;
    },
  };
  let state;
  const restored = await factory()(tools).restoreMachine(
    {
      enterpriseKey: "demo-enterprise",
      workflowType: "weekly-business-report",
    },
    async (value) => {
      state = value;
    },
    async (page) => {
      archived.push(page);
      return "local-page-" + archived.length;
    },
  );
  assert.equal(restored.configurationVersion, 7);
  assert.equal(restored.hostSnapshot.cron, "current-confirmed-schedule");
  assert.equal(restored.pendingActionCount, 1);
  assert.equal(restored.recoveryItemCounts.open, 1);
  assert.equal(restored.recoveryItemCounts.waived, 1);
  assert.equal(
    archived.find((p) => p.kind === "pending_actions").actions[0]
      .correlationMarker,
    "original-provider-marker",
  );
  assert.equal(archived.filter((p) => p.kind === "migration_chunk").length, 2);
  assert.equal(state.restorationComplete, true);
  assert.equal(restored.readyForActivation, false);
  assert.equal(created, 0);
});

test("the actual local audit bridge persists redacted full errors and preserves the tool result", async () => {
  const os = require("node:os"),
    cp = require("node:child_process");
  const run = fs.realpathSync(
    fs.mkdtempSync(path.join(os.tmpdir(), "smedc-audit-")),
  );
  const logger = path.join(__dirname, "../scripts/audit_log.py");
  const source = fs.readFileSync(
    path.join(__dirname, "../scripts/audited-tool.js"),
    "utf8",
  );
  const audit = vm.runInNewContext(source);
  const original = {
    isError: true,
    content: [
      { type: "text", text: "Synthetic full failure; Bearer SYNTHETIC_SECRET" },
    ],
  };
  try {
    const tools = {
      exec_command: async ({ cmd }) => {
        try {
          return {
            exit_code: 0,
            output: cp.execFileSync("/bin/sh", ["-c", cmd], {
              encoding: "utf8",
            }),
          };
        } catch (error) {
          return {
            exit_code: error.status,
            output: String(error.stdout) + String(error.stderr),
          };
        }
      },
    };
    const result = await audit(
      tools,
      logger,
      run,
      { stage: "query", tool: "synthetic", effect: "read" },
      async () => original,
      "python3",
    );
    assert.equal(result, original);
    const file = fs
      .readdirSync(path.join(run, "call-audit"))
      .find((name) => name.endsWith(".json"));
    const persisted = JSON.parse(
      fs.readFileSync(path.join(run, "call-audit", file), "utf8"),
    );
    assert.equal(persisted.status, "failed");
    assert(!JSON.stringify(persisted).includes("SYNTHETIC_SECRET"));
    assert(JSON.stringify(persisted).includes("Synthetic full failure"));
  } finally {
    fs.rmSync(run, { recursive: true, force: true });
  }
});
test("a clear Gmail send receipt confirms observable attachment identity without invented MIME bytes, while unknown recovery stays unknown", async () => {
  const crypto = require("node:crypto");
  const html = "<html>Verified final report</html>";
  const artifactHash = crypto.createHash("sha256").update(html).digest("hex");
  let sends = 0,
    confirmed = 0;
  const identity = {
    kind: "email",
    purpose: "weekly_report",
    sender: "sender@example.test",
    recipients: ["owner@example.test"],
    storeNames: ["Demo"],
    window: { startDate: "2026-10-26", endDate: "2026-11-01" },
    deliveryVersion: 1,
  };
  const intent = {
    actionId: "clear-send",
    identity,
    artifactHash,
    correlationMarker: "exact-marker",
  };
  const tools = {
    mcp__smedc__manage_workflow_run: async () => ({}),
    mcp__smedc__record_workflow_action: async ({ operation }) => {
      if (operation.kind === "intent")
        return {
          actions: [
            {
              actionId: intent.actionId,
              state: "intent",
              permitted: true,
              identityHash: "a".repeat(64),
            },
          ],
        };
      if (operation.kind === "get")
        return {
          actions: [
            { ...intent, state: "unknown", identityHash: "a".repeat(64) },
          ],
        };
      if (
        operation.receipts?.[0].state === "confirmed" ||
        operation.receipt?.state === "confirmed"
      )
        confirmed++;
      return { recorded: 1 };
    },
    mcp__codex_apps__gmail_get_profile: async () => ({
      email_address: "sender@example.test",
    }),
    mcp__codex_apps__gmail_send_email: async () => {
      sends++;
      return { id: "actual-send-id" };
    },
    mcp__codex_apps__gmail_read_email_thread: async () => ({
      messages: [
        {
          message_id: "actual-send-id",
          from: { email: "sender@example.test" },
          to: [{ email: "owner@example.test" }],
          cc: [],
          bcc: [],
          subject: "Weekly [exact-marker]",
          attachments: [
            {
              filename: "final.html",
              attachment_id: "actual-attachment-id",
              size: Buffer.byteLength(html),
              mime_type: "text/html",
            },
          ],
        },
      ],
    }),
    mcp__codex_apps__gmail_search_email_ids: async () => ({
      message_ids: ["actual-send-id"],
    }),
  };
  const session = {
    workflowId: "w",
    installationId: "i",
    runId: "r",
    assignmentEpoch: 1,
    controlVersion: 1,
  };
  const native = factory()(tools, { saveOutcome: async () => {} });
  const sent = await native.sendEmail(session, intent, {
    artifactHash,
    subject: "Weekly",
    payload: {
      mime_type: "multipart/mixed",
      parts: [
        { mime_type: "text/html", body: { content: "Report summary" } },
        {
          mime_type: "text/html",
          filename: "final.html",
          content_disposition: "attachment",
          body: { content: html },
        },
      ],
    },
  });
  assert.equal(sent.state, "confirmed");
  assert.equal(sends, 1);
  assert.equal(confirmed, 1);
  const recovered = await native.reconcileEmail(session, intent, {
    identityHash: "a".repeat(64),
  });
  assert.equal(recovered.state, "unknown");
  assert.equal(sends, 1);
  assert.equal(confirmed, 1);
});
test("package maintenance updates the same paused native task and preserves its schedule/model", async () => {
  let actual,
    creates = 0,
    updates = 0;
  const tools = {
    mcp__codex_app__list_projects: async () => ({
      projects: [{ id: "project-new", type: "local" }],
    }),
    mcp__codex_app__automation_update: async (input) => {
      if (input.mode === "create") {
        creates++;
        actual = { ...hostTask, ...input, id: "task-new" };
      }
      if (input.mode === "update") {
        updates++;
        actual = { ...actual, ...input };
      }
      return { automationId: "task-new" };
    },
    exec_command: async () => ({
      exit_code: 0,
      output: JSON.stringify(actual),
    }),
  };
  const native = factory()(tools, { localScript: "/isolated/workflow.py" }),
    journal = {};
  const input = {
    workflowId: "flow",
    name: "Example",
    prompt: "Use installed workflow",
    rrule: hostTask.rrule,
    model: hostTask.model,
    reasoningEffort: "high",
    projectId: "project-new",
    platform: "macos",
    timezone: "Asia/Shanghai",
  };
  await native.install(input, journal, async () => {});
  await native.install(
    { ...input, prompt: "Use updated versioned workflow", update: true },
    journal,
    async () => {},
  );
  assert.equal(creates, 1);
  assert.equal(updates, 1);
  assert.equal(actual.prompt, "Use updated versioned workflow");
  assert.equal(actual.rrule, hostTask.rrule);
  assert.equal(actual.model, hostTask.model);
  assert.equal(journal.taskId, "task-new");
});
test("activation cannot mutate central installation state while its real local host task is active", async () => {
  let mutations = 0;
  const tools = {
    mcp__smedc__get_enterprise_workflow: async () => ({
      workflowId: "w",
      assignedInstallationId: "i",
      controlState: "active",
      capability: {
        id: "enterprise-workflows-v1",
        version: "1.0.0",
        configurationSchemaVersion: 1,
        minimumLauncherVersion: "0.16.0",
      },
    }),
    exec_command: async () => ({
      exit_code: 0,
      output: JSON.stringify({ id: "task", kind: "cron", status: "ACTIVE" }),
    }),
    mcp__smedc__manage_workflow_installation: async () => {
      mutations++;
    },
  };
  const native = factory()(tools, { localScript: "/isolated/workflow.py" });
  await assert.rejects(
    native.activate(
      {
        workflowId: "w",
        enterpriseKey: "demo",
        workflowType: "meituan-daily-ingestion",
        installationId: "i",
        handoff: {
          kind: "legacy_paused",
          acknowledged: true,
          proofHash: "a".repeat(64),
          confirmedAt: "2026-11-02T00:00:00Z",
        },
      },
      { workflowId: "w", taskId: "task", hostSnapshot: { taskId: "task" } },
      async () => {},
    ),
    /PAUSED/,
  );
  assert.equal(mutations, 0);
});

test("the native bridge refuses missing official bindings and foreign server suffix matches", async () => {
  let calls = 0;
  const tools = {
    mcp__smedc__get_enterprise_workflow: async () => {
      calls++;
    },
    mcp__other__get_enterprise_workflow: async () => {
      calls++;
    },
  };
  await assert.rejects(
    factory()(tools, { officialBinding: null }).getWorkflow({
      enterpriseKey: "demo",
      workflowType: "weekly-business-report",
    }),
    /core-verified/,
  );
  await assert.rejects(
    factory()(tools, {
      smedcTools: {
        get_enterprise_workflow: "mcp__other__get_enterprise_workflow",
      },
    }).getWorkflow({
      enterpriseKey: "demo",
      workflowType: "weekly-business-report",
    }),
    /Nonofficial/,
  );
  assert.equal(calls, 0);
});
test("the concrete exec bridge roundtrips shell metacharacters as JSON data without executing them", async () => {
  const os = require("node:os"),
    cp = require("node:child_process");
  const run = fs.realpathSync(
      fs.mkdtempSync(path.join(os.tmpdir(), "smedc-shell-")),
    ),
    sentinel = path.join(run, "must-not-exist");
  const text =
    "Synthetic ' \" $(touch " +
    sentinel +
    ") `touch " +
    sentinel +
    "`\nStore 😀";
  const expected = {
    enterpriseName: text,
    storeName: text,
    sourceAccount: text,
  };
  try {
    const tools = {
      exec_command: async ({ cmd }) => {
        try {
          return {
            exit_code: 0,
            output: cp.execFileSync("/bin/sh", ["-c", cmd], {
              encoding: "utf8",
            }),
          };
        } catch (error) {
          return {
            exit_code: error.status,
            output: String(error.stdout) + String(error.stderr),
          };
        }
      },
    };
    const native = factory()(tools, {
      localScript: path.join(__dirname, "../scripts/workflow.py"),
    });
    const target = path.join(run, "state's data.json");
    await native.saveLocal(target, expected);
    assert.deepEqual(JSON.parse(fs.readFileSync(target, "utf8")), expected);
    assert.equal(fs.existsSync(sentinel), false);
    const alias = path.join(run, "alias");
    fs.symlinkSync(run, alias, "dir");
    await assert.rejects(
      native.saveLocal(path.join(alias, "rejected.json"), expected),
      (error) =>
        error.code === "LOCAL_CHECKPOINT_PERSISTENCE_FAILED" &&
        error.exitCode === 2 &&
        error.message.includes("Canonical state path required") &&
        error.toolResult.output.includes("Canonical state path required"),
    );
    assert.equal(fs.existsSync(path.join(run, "rejected.json")), false);
  } finally {
    fs.rmSync(run, { recursive: true, force: true });
  }
});

test("a partially claimed notification batch is not reported wholly confirmed or sent again", async () => {
  const crypto = require("node:crypto"),
    body = "<p>Two synthetic new drafts</p>",
    artifactHash = crypto.createHash("sha256").update(body).digest("hex");
  let sends = 0;
  const tools = {
    mcp__smedc__manage_workflow_run: async () => ({}),
    mcp__codex_apps__gmail_get_profile: async () => ({
      emailAddress: "sender@example.test",
    }),
    mcp__smedc__record_workflow_action: async () => ({
      actions: [
        {
          actionId: "legacy-notification",
          state: "confirmed",
          permitted: false,
          conflictActionIds: ["legacy-notification"],
          claimedItems: 1,
          requestedItems: 2,
          identityHash: "a".repeat(64),
        },
      ],
    }),
    mcp__codex_apps__gmail_send_email: async () => {
      sends++;
    },
  };
  const native = factory()(tools, { saveOutcome: async () => {} });
  const result = await native.sendEmail(
    {
      workflowId: "w",
      installationId: "i",
      runId: "r",
      assignmentEpoch: 1,
      controlVersion: 1,
    },
    {
      actionId: "notification",
      artifactHash,
      correlationMarker: "marker",
      identity: {
        kind: "email",
        purpose: "review_drafts",
        sender: "sender@example.test",
        recipients: ["owner@example.test"],
      },
    },
    {
      subject: "Drafts",
      artifactHash,
      payload: { mime_type: "text/html", body: { content: body } },
    },
  );
  assert.equal(result.state, "unknown");
  assert.equal(result.partialOverlap, true);
  assert.equal(sends, 0);
});

test("a cold claimant follows the server's original action ID when reconciling confirmed mail", async () => {
  const receipt = {
    actionId: "legacy-mail",
    state: "confirmed",
    receiptId: "sent-original",
  };
  let lookup;
  const native = factory()({
    mcp__smedc__manage_workflow_run: async () => ({ allowed: true }),
    mcp__smedc__record_workflow_action: async ({ operation }) => {
      if (operation.kind === "intent")
        return {
          actions: [
            {
              actionId: "legacy-mail",
              state: "confirmed",
              permitted: false,
              conflictActionIds: ["legacy-mail"],
              claimedItems: 1,
              requestedItems: 1,
              receipt,
            },
          ],
        };
      assert.equal(operation.kind, "get");
      lookup = [...operation.actionIds];
      return {
        actions: [{ actionId: "legacy-mail", state: "confirmed", receipt }],
      };
    },
  });
  const session = {
    workflowId: "flow",
    runId: "run",
    installationId: "mac",
    assignmentEpoch: 1,
    controlVersion: 1,
  };
  const intent = { actionId: "new-local-id", identity: { kind: "email" } };
  const claimed = await native.claim(session, intent);
  assert.equal(claimed.permitted, false);
  const result = await native.reconcileEmail(session, intent, claimed);
  assert.deepEqual(lookup, ["legacy-mail"]);
  assert.equal(result.receipt.receiptId, "sent-original");
});

test("host readback records a user changed schedule instead of restoring a stale snapshot", async () => {
  let recorded;
  const actual = {
    id: "task",
    kind: "cron",
    status: "PAUSED",
    execution_environment: "local",
    name: "Example",
    prompt: "Use workflow",
    target: { type: "projectless" },
    rrule: "RRULE:FREQ=DAILY;BYHOUR=9;BYMINUTE=15",
    model: "gpt-6.1-sol",
    reasoning_effort: "high",
    notification_policy: "failed_runs_only",
  };
  const tools = {
    exec_command: async () => ({
      exit_code: 0,
      output: JSON.stringify(actual),
    }),
    mcp__codex_app__automation_update: async () => ({ automationId: "task" }),
    mcp__smedc__manage_workflow_installation: async ({ operation }) => {
      recorded = operation.hostSnapshot;
      return { version: 2 };
    },
  };
  const journal = {
    workflowId: "w",
    taskId: "task",
    hostSnapshot: {
      host: "codex",
      platform: "macos",
      taskId: "task",
      projectRef: "projectless",
      cron: "old-schedule",
      timezone: "Asia/Shanghai",
      model: "old-model",
      reasoningEffort: "low",
      state: "paused",
    },
  };
  await factory()(tools, { localScript: "/isolated/workflow.py" }).setHostState(
    { workflowId: "w", installationId: "i" },
    journal,
    "paused",
    async () => {},
  );
  assert.equal(recorded.cron, actual.rrule);
  assert.equal(recorded.model, actual.model);
  assert.equal(recorded.reasoningEffort, "high");
});

test("openRun rebinds the original run to current verified control and assignment", async () => {
  const snapshot = {
    workflowType: "meituan-daily-ingestion",
    window: { startDate: "2026-10-01", endDate: "2026-10-01" },
    configuration: { datasets: ["business"] },
  };
  const current = {
    capability: {
      id: "enterprise-workflows-v1",
      version: "1.0.0",
      configurationSchemaVersion: 1,
      minimumLauncherVersion: "0.16.0",
    },
    workflowId: "flow",
    controlState: "active",
    assignedInstallationId: "mac-a",
    assignmentEpoch: 1,
    controlVersion: 5,
  };
  const persisted = {
    workflowId: "flow",
    runId: "original-run",
    installationId: "mac-a",
    assignmentEpoch: 1,
    controlVersion: 2,
    snapshot,
  };
  const native = factory()({
    mcp__smedc__get_enterprise_workflow: async () => current,
    mcp__smedc__manage_workflow_run: async ({ workflowId, operation }) => {
      assert.equal(workflowId, "flow");
      assert.equal(operation.kind, "resume");
      assert.equal(operation.runId, "original-run");
      assert.equal(operation.installationId, current.assignedInstallationId);
      assert.equal(operation.assignmentEpoch, current.assignmentEpoch);
      assert.equal(operation.controlVersion, current.controlVersion);
      return { runId: "original-run", snapshot };
    },
  });
  const input = {
    enterpriseKey: "demo",
    workflowType: snapshot.workflowType,
    installationId: "mac-a",
    resume: persisted,
  };
  const resumed = await native.openRun(input);
  assert.deepEqual(resumed.snapshot, snapshot);
  current.assignedInstallationId = "mac-b";
  current.assignmentEpoch = 2;
  const adopted = await native.openRun({ ...input, installationId: "mac-b" });
  assert.equal(adopted.runId, "original-run");
  assert.deepEqual(adopted.snapshot.window, snapshot.window);
  await assert.rejects(native.openRun(input), /assigned elsewhere/);
});

test("cold recovery discovers an unfinished run on a later page instead of starting twice", async () => {
  const operations = [];
  const snapshot = {
    workflowType: "meituan-daily-ingestion",
    window: { startDate: "2026-11-02", endDate: "2026-11-02" },
  };
  const native = factory()({
    mcp__smedc__get_enterprise_workflow: async () => ({
      capability: {
        id: "enterprise-workflows-v1",
        version: "1.0.0",
        configurationSchemaVersion: 1,
        minimumLauncherVersion: "0.16.0",
      },
      workflowId: "flow",
      controlState: "active",
      assignedInstallationId: "mac",
      assignmentEpoch: 2,
      controlVersion: 3,
    }),
    mcp__smedc__get_workflow_status: async ({ cursor }) => ({
      workflowId: "flow",
      runs: cursor
        ? [
            {
              id: "original",
              finishedAt: null,
              workflowPackageVersion: "1.0.4",
            },
          ]
        : [{ id: "finished", finishedAt: "2026-11-01T00:00:00Z" }],
      nextCursor: cursor ? null : "page-2",
    }),
    mcp__smedc__manage_workflow_run: async ({ operation }) => {
      operations.push(operation);
      if (operation.kind === "start") throw new Error("WORKFLOW_BUSY");
      return { runId: "original", snapshot };
    },
  });
  const run = await native.recoverRun({
    workflowId: "flow",
    enterpriseKey: "demo",
    workflowType: snapshot.workflowType,
    installationId: "mac",
    packageVersion: "1.0.4",
    window: { startDate: "2026-11-03", endDate: "2026-11-03" },
  });
  assert.equal(run.runId, "original");
  assert.equal(run.snapshot.window.startDate, "2026-11-02");
  assert.equal(operations.length, 1);
  assert.equal(operations[0].kind, "resume");
  await assert.rejects(
    native.recoverRun({
      workflowId: "flow",
      enterpriseKey: "demo",
      workflowType: snapshot.workflowType,
      installationId: "mac",
      packageVersion: "1.0.5",
    }),
    /original package version/,
  );
  assert.equal(operations.length, 1);
});

test("scheduled Goal uses the host lifecycle and reuses the active Goal after continuation", async () => {
  let goal = null,
    created = 0;
  const native = factory()({
    get_goal: async () => ({ goal }),
    create_goal: async ({ objective }) => {
      created++;
      goal = { objective, status: "active" };
      return { goal };
    },
  });
  await assert.rejects(native.beginGoal({ workflowId: "flow" }), /Explicit/);
  await native.beginGoal({ workflowId: "flow", goalRequested: true });
  await native.beginGoal({ workflowId: "flow", goalRequested: true });
  assert.equal(created, 1);
  await assert.rejects(
    native.beginGoal({ workflowId: "other", goalRequested: true }),
    /different active/,
  );
});

test("cold action recovery discovers terminal receipts without local action IDs and saves every page", async () => {
  const pages = [],
    reads = [];
  const native = factory()({
    mcp__smedc__get_workflow_status: async (input) => {
      assert.equal(input.workflowId, "flow");
      assert.equal(input.runId, "run");
      assert.equal(input.limit, 100);
      if (!input.actionCursor)
        return {
          workflowId: "flow",
          runActionRefs: [{ actionId: "a", runId: "run", state: "confirmed" }],
          nextRunActionCursor: "a",
        };
      assert.equal(input.actionCursor, "a");
      assert.equal(pages.length, 1, "persist before fetching the next page");
      return {
        workflowId: "flow",
        runActionRefs: [
          { actionId: "b", runId: "run", state: "unknown" },
          { actionId: "c", runId: "run", state: "failed" },
        ],
        nextRunActionCursor: null,
      };
    },
    mcp__smedc__record_workflow_action: async ({ operation }) => {
      assert.equal(operation.kind, "get");
      reads.push([...operation.actionIds]);
      return {
        actions: operation.actionIds.map((actionId) => ({
          actionId,
          runId: "run",
          state: { a: "confirmed", b: "unknown", c: "failed" }[actionId],
          receipt: {
            state: { a: "confirmed", b: "unknown", c: "failed" }[actionId],
            providerReceiptId: "synthetic-" + actionId,
          },
        })),
      };
    },
  });
  const result = await native.recoverActions(
    { workflowId: "flow", runId: "run" },
    async (page) => pages.push(page),
  );
  assert.equal(result.actionCount, 3);
  assert.equal(result.confirmed, 1);
  assert.equal(result.unresolved, 1);
  assert.equal(result.failed, 1);
  assert.deepEqual(reads, [["a"], ["b", "c"]]);
  assert.equal(pages[0].actions[0].receipt.providerReceiptId, "synthetic-a");
});

test("cold action recovery fails closed on an old service or a foreign run", async () => {
  let response = { workflowId: "flow", pendingActions: [] },
    lookups = 0;
  const native = factory()({
    mcp__smedc__get_workflow_status: async () => response,
    mcp__smedc__record_workflow_action: async () => {
      lookups++;
      return { actions: [] };
    },
  });
  const input = { workflowId: "flow", runId: "run" };
  await assert.rejects(
    native.recoverActions(input, async () => {}),
    /inventory unavailable/,
  );
  response = {
    workflowId: "flow",
    runActionRefs: [{ actionId: "a", runId: "other", state: "confirmed" }],
    nextRunActionCursor: null,
  };
  await assert.rejects(
    native.recoverActions(input, async () => {}),
    /cross-run/,
  );
  assert.equal(lookups, 0);
});

test("a blank daily host reuses the completed current window instead of creating duplicate work", async () => {
  const window = { startDate: "2026-11-02", endDate: "2026-11-02" };
  let starts = 0,
    workflowType = "meituan-daily-ingestion";
  const native = factory()({
    mcp__smedc__get_enterprise_workflow: async () => ({
      capability: {
        id: "enterprise-workflows-v1",
        version: "1.0.0",
        configurationSchemaVersion: 1,
        minimumLauncherVersion: "0.16.0",
      },
      workflowId: "flow",
      controlState: "active",
      assignedInstallationId: "mac",
      assignmentEpoch: 1,
      controlVersion: 3,
      version: 3,
      integration: { version: 2 },
    }),
    mcp__smedc__get_workflow_status: async () => ({
      workflowId: "flow",
      workflowType,
      assignedInstallationId: "mac",
      controlState: "active",
      observedAt: new Date().toISOString(),
      installations: [readyInstallation()],
      nextCursor: null,
      runs: [
        {
          id: "finished-original",
          status: "succeeded",
          finishedAt: "2026-11-03T03:00:00Z",
          snapshot: {
            workflowType,
            configurationVersion: 3,
            integrationVersion: 2,
            window,
          },
          summary: { status: "succeeded" },
        },
      ],
    }),
    mcp__smedc__manage_workflow_run: async ({ operation }) => {
      starts++;
      assert.equal(operation.kind, "start");
      return { runId: "fresh-run", snapshot: { workflowType, window } };
    },
  });
  const result = await native.recoverRun({
    workflowId: "flow",
    enterpriseKey: "demo",
    workflowType: "meituan-daily-ingestion",
    installationId: "mac",
    packageVersion: "1.0.6",
    window,
  });
  assert.equal(result.alreadyCompleted, true);
  assert.equal(result.runId, "finished-original");
  assert.equal(starts, 0);
  workflowType = "meituan-review-operations";
  const input = {
    workflowId: "flow",
    enterpriseKey: "demo",
    installationId: "mac",
    packageVersion: "1.0.6",
    window,
  };
  assert.equal(
    (await native.recoverRun({ ...input, workflowType })).runId,
    "fresh-run",
  );
  workflowType = "meituan-daily-ingestion";
  assert.equal(
    (
      await native.recoverRun({
        ...input,
        workflowType,
        backfill: { confirmationDigest: "synthetic-approved-preview" },
      })
    ).runId,
    "fresh-run",
  );
  assert.equal(starts, 2);
});

test("installation without an explicit schedule creates no native task", async () => {
  let creates = 0;
  const native = factory()({
    mcp__codex_app__automation_update: async () => {
      creates++;
    },
  });
  await assert.rejects(
    native.install(
      {
        workflowId: "flow",
        projectId: null,
        prompt: "Use workflow",
        name: "Example",
        model: "available-model",
        reasoningEffort: "high",
        timezone: "Asia/Shanghai",
        platform: "macos",
      },
      {},
      async () => {},
    ),
    /needs_configuration/,
  );
  assert.equal(creates, 0);
});

const preflightCapabilities = [
  "configuration", "permissions", "workspace", "dependencies", "host_schedule",
  "host_timezone", "host_model", "meituan_reviews", "download", "meituan_erp",
];
function readyInstallation() {
  return {
    installationId: "mac", state: "enabled", hostSnapshot: {},
    workflowPackageVersion: "1.0.6", firstRunVerification: "verified",
    readinessChecks: preflightCapabilities.map((capability) => ({
      capability, status: "ready", checkedAt: new Date().toISOString(),
    })),
  };
}
test("expired or missing checks stop a new run until actual results are recorded", async () => {
  const installation = readyInstallation();
  const workflowType = "meituan-review-operations";
  const input = { workflowId: "flow", workflowType, installationId: "mac", packageVersion: "1.0.6" };
  installation.readinessChecks.find(c => c.capability === "meituan_reviews").checkedAt =
    new Date(Date.now() - 86400000).toISOString();
  installation.readinessChecks = installation.readinessChecks.filter(c => c.capability !== "workspace");
  installation.readinessChecks.find(c => c.capability === "download").status = "unsupported";
  const operations = [];
  const starts = [];
  const native = factory()({
    mcp__smedc__get_enterprise_workflow: async () => ({
      capability: {
        id: "enterprise-workflows-v1", version: "1.0.0",
        configurationSchemaVersion: 1, minimumLauncherVersion: "0.16.0",
      },
      workflowId: "flow", assignedInstallationId: "mac", controlState: "active",
      version: 1, integration: { version: 1 }, assignmentEpoch: 1, controlVersion: 1,
    }),
    mcp__smedc__manage_workflow_run: async ({ operation }) => {
      starts.push(operation.kind);
      assert.equal(operations.length, 2);
      return { runId: "new-run", snapshot: { workflowType } };
    },
    mcp__smedc__get_workflow_status: async () => ({
      ...input, observedAt: new Date().toISOString(), installations: [installation],
      assignedInstallationId: "mac", controlState: "active",
    }),
    mcp__smedc__manage_workflow_installation: async ({ operation }) => {
      operations.push(operation);
      installation.readinessChecks = operation.checks;
      return installation;
    },
  });
  await assert.rejects(native.openRun(input), /workspace, meituan_reviews/);
  assert.equal(operations.length, 0);
  const recheck = (status) => async (names) => {
    assert.deepEqual(Array.from(names), status === "ready" ? ["meituan_reviews"] : ["workspace", "meituan_reviews"]);
    return Array.from(names, capability => ({
      capability, status: capability === "meituan_reviews" ? status : "ready",
      checkedAt: new Date(Date.now() - (status === "ready" ? 0 : 1000)).toISOString(),
    }));
  };
  await assert.rejects(native.openRun({ ...input, refreshChecks: recheck("needs_login") }), /meituan_reviews/);
  assert.equal(operations[0].kind, "record_checks");
  assert.equal(operations[0].firstRunVerification, "verified");
  assert.equal(starts.length, 0);
  assert.equal((await native.openRun({ ...input, refreshChecks: recheck("ready") })).runId, "new-run");
  assert.deepEqual(starts, ["start"]);
  await native.ensureRunReadiness(input);
  assert.equal(operations.length, 2);
  assert.equal(installation.readinessChecks.find(c => c.capability === "download").status, "unsupported");
});

test("preserves a structured same-receipt rejection without inferring it from prose", () => {
  const native = factory()({});
  const failure = (body) => ({ isError: true, content: [{ type: "text", text: body }] });
  assert.throws(
    () => native.unwrap(failure(JSON.stringify({ error: { code: "RECEIPT_ID_CONFLICT" } }))),
    { code: "RECEIPT_ID_CONFLICT" },
  );
  assert.throws(
    () => native.unwrap(failure("Timeout while checking for RECEIPT_ID_CONFLICT")),
    { code: "TOOL_REJECTED" },
  );
});
