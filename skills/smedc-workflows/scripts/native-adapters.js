/* Evaluate this function expression in the invoking host with its actual tools object.
   No network, credentials, scheduler file writes or alternate SMEDC client. */
(function createNativeAdapters(tools, options = {}) {
  const names = {
    projects: "mcp__codex_app__list_projects",
    automation: "mcp__codex_app__automation_update",
    profile: "mcp__codex_apps__gmail_get_profile",
    send: "mcp__codex_apps__gmail_send_email",
    search: "mcp__codex_apps__gmail_search_email_ids",
    read: "mcp__codex_apps__gmail_read_email_thread",
    archive: "mcp__codex_app__set_thread_archived",
  };
  const now = () => new Date().toISOString();
  const pythonExecutable = options.pythonExecutable ?? "python3";
  function unwrap(result) {
    if (!result) throw new Error("TOOL_UNAVAILABLE");
    if (result.isError) {
      const code =
        JSON.stringify(result).match(
          /\b(?:WORKFLOW|ORDER_SCOPE|AUTH|LAUNCHER|SMEDC)_[A-Z_]+\b/,
        )?.[0] ?? "TOOL_REJECTED";
      const error = new Error(code);
      error.code = code;
      error.toolResult = redactJournal(result);
      throw error;
    }
    let data = result.structuredContent;
    if (data === undefined && Array.isArray(result.content)) {
      const values = result.content
        .filter((c) => c.type === "text")
        .map((c) => {
          try {
            return JSON.parse(c.text);
          } catch {
            return undefined;
          }
        })
        .filter((v) => v !== undefined);
      if (values.length !== 1)
        throw new Error("No unambiguous structured tool response");
      data = values[0];
    }
    data ??= result;
    if (data.ok === false || data.error) {
      const code =
        typeof data.error?.code === "string" &&
        /^[A-Z0-9_]+$/.test(data.error.code)
          ? data.error.code
          : "TOOL_REJECTED";
      const error = new Error(code);
      error.code = code;
      error.toolResult = redactJournal(result);
      throw error;
    }
    return data.data ?? data;
  }
  async function call(name, input) {
    if (typeof tools[name] !== "function")
      throw new Error("unsupported: missing native tool " + name);
    return unwrap(await tools[name](input));
  }
  async function mcp(name, input) {
    const binding = options.officialBinding;
    if (
      !binding ||
      binding.entryName !== "smedc" ||
      binding.namespace !== "mcp__smedc__" ||
      binding.serviceOrigin !== "https://api.smedatacenter.xyz"
    )
      throw new Error("Official core-verified smedc binding required");
    const expected = binding.namespace + name;
    const actual = options.smedcTools?.[name] ?? expected;
    if (actual !== expected)
      throw new Error("Nonofficial or ambiguous SMEDC tool binding");
    return call(actual, input);
  }
  function bind(session) {
    const { installationId, runId, assignmentEpoch, controlVersion } = session;
    if (
      !installationId ||
      !runId ||
      !Number.isInteger(assignmentEpoch) ||
      !Number.isInteger(controlVersion)
    )
      throw new Error("Incomplete live run binding");
    return { installationId, runId, assignmentEpoch, controlVersion };
  }
  function firstAction(result, id) {
    const a = result.actions?.[0];
    if (
      !a ||
      result.actions.length !== 1 ||
      (a.actionId !== id &&
        !(
          a.permitted === false &&
          Array.isArray(a.conflictActionIds) &&
          a.conflictActionIds.includes(a.actionId)
        ))
    )
      throw new Error("Missing or unbound action result");
    return a;
  }
  const quote = (value) => "'" + String(value).replace(/'/g, "'\"'\"'") + "'";
  async function runLocalCommand(input) {
    let result = await tools.exec_command(input),
      output = result.output ?? "";
    while (result.session_id) {
      if (typeof tools.write_stdin !== "function") {
        const error = new Error(
          "Local operation still running; resume original session",
        );
        error.sessionId = result.session_id;
        throw error;
      }
      result = await tools.write_stdin({
        session_id: result.session_id,
        chars: "",
        yield_time_ms: 10000,
        max_output_tokens: input.max_output_tokens ?? 10000,
      });
      output += result.output ?? "";
    }
    return { ...result, output };
  }
  function redactJournal(value) {
    if (Array.isArray(value)) return value.map(redactJournal);
    if (value && typeof value === "object")
      return Object.fromEntries(
        Object.entries(value).map(([key, item]) => [
          key,
          /authorization|cookie|password|secret|access.?token|refresh.?token|api.?key/i.test(
            key,
          )
            ? "<REDACTED>"
            : redactJournal(item),
        ]),
      );
    if (typeof value === "string")
      return value
        .replace(/\bBearer\s+[^\s"']+/gi, "Bearer <REDACTED>")
        .replace(
          /(authorization|cookie|password|access_token|refresh_token|api_key)\s*[:=]\s*[^\r\n]+/gi,
          "$1: <REDACTED>",
        );
    return value;
  }
  function localError(code, message, result) {
    const details = redactJournal(result);
    const reason = String(details.output ?? "").trim();
    const error = new Error(
      message +
        " (exit " +
        String(result.exit_code) +
        ")" +
        (reason ? ": " + reason.slice(0, 2000) : ""),
    );
    return Object.assign(error, {
      code,
      exitCode: result.exit_code,
      toolResult: details,
    });
  }
  async function prepareWorkspace(input) {
    if (!options.localScript || typeof tools.exec_command !== "function")
      throw new Error("Local helper unavailable");
    const result = await runLocalCommand({
      cmd:
        quote(pythonExecutable) +
        " " +
        quote(options.localScript) +
        " prepare-workspace --json " +
        quote(JSON.stringify(input)),
      max_output_tokens: 1500,
    });
    if (result.exit_code !== 0)
      throw localError(
        "WORKSPACE_PREFLIGHT_FAILED",
        "Workspace preflight failed",
        result,
      );
    return JSON.parse(result.output);
  }
  async function saveLocal(path, value) {
    if (!options.localScript || typeof tools.exec_command !== "function")
      throw new Error("Local helper unavailable");
    const text = JSON.stringify(value),
      checksum = sha256(utf8(text));
    const uploadId =
      "state-" +
      Date.now().toString(36) +
      "-" +
      Math.random().toString(36).slice(2, 12);
    let offset = 0;
    for (let start = 0; start < text.length;) {
      let end = Math.min(start + 24000, text.length);
      if (
        end < text.length &&
        text.charCodeAt(end - 1) >= 0xd800 &&
        text.charCodeAt(end - 1) <= 0xdbff
      )
        end--;
      const part = text.slice(start, end),
        final = end === text.length;
      const input = {
        path,
        uploadId,
        offset,
        text: part,
        final,
        checksumSha256: checksum,
      };
      const result = await runLocalCommand({
        cmd:
          quote(pythonExecutable) +
          " " +
          quote(options.localScript) +
          " save-chunk --json " +
          quote(JSON.stringify(input)),
        max_output_tokens: 300,
      });
      if (result.exit_code !== 0)
        throw localError(
          "LOCAL_CHECKPOINT_PERSISTENCE_FAILED",
          "Local checkpoint persistence failed",
          result,
        );
      offset += utf8(part).length;
      start = end;
    }
    return { saved: true };
  }
  async function readHostDefinition(taskId) {
    if (!/^[A-Za-z0-9_-]{1,64}$/.test(taskId))
      throw new Error("Unsafe native task identity");
    if (!options.localScript || typeof tools.exec_command !== "function")
      throw new Error(
        "unsupported: native TOML readback requires the local helper and exec tool",
      );
    const result = await runLocalCommand({
      cmd:
        quote(pythonExecutable) +
        " " +
        quote(options.localScript) +
        " host-read --json " +
        quote(JSON.stringify({ taskId })),
      max_output_tokens: 8000,
    });
    if (result.exit_code !== 0)
      throw Object.assign(new Error("Native definition readback failed"), {
        toolResult: redactJournal(result),
      });
    return JSON.parse(result.output);
  }
  async function install(input, journal, save) {
    if (input.platform !== "macos" || input.timezone !== "Asia/Shanghai")
      throw new Error("unsupported: macOS and Asia/Shanghai required");
    if (
      !input.model ||
      !input.reasoningEffort ||
      !input.name ||
      !input.prompt ||
      !input.rrule ||
      !input.workflowId ||
      input.projectId === undefined
    )
      throw new Error(
        "needs_configuration: verify host task fields, model and effort",
      );
    if (input.projectId !== null) {
      const projects = await call(names.projects, {});
      const project = (projects.projects ?? projects).find?.(
        (p) => (p.projectId ?? p.id) === input.projectId,
      );
      if (!project || project.type === "remote" || project.kind === "remote")
        throw new Error(
          "needs_configuration: add/select a local project in Codex",
        );
    } else if (!input.workspaceVerified || !input.workspace)
      throw new Error(
        "needs_configuration: verify an isolated writable local workspace",
      );
    if (journal.workflowId && journal.workflowId !== input.workflowId)
      throw new Error("Installation journal belongs to another workflow");
    if (journal.createPending && !journal.taskId)
      throw new Error(
        "unknown: inspect host automations and bind the original task before retry",
      );
    const expected = {
      kind: "cron",
      destination: "local",
      executionEnvironment: "local",
      projectId: input.projectId,
      model: input.model,
      reasoningEffort: input.reasoningEffort,
      name: input.name,
      prompt: input.prompt,
      rrule: input.rrule,
      notificationPolicy: "failed_runs_only",
      status: "PAUSED",
    };
    const alreadyInstalled = Boolean(journal.taskId);
    if (!journal.taskId) {
      Object.assign(journal, {
        workflowId: input.workflowId,
        createPending: true,
        createRequestedAt: now(),
      });
      await save(journal); // Durable intent BEFORE scheduler mutation; unknown never blindly retries.
      const created = await call(names.automation, {
        mode: "create",
        ...expected,
      });
      journal.taskId =
        created.id ?? created.automation?.id ?? created.automationId;
      if (!journal.taskId)
        throw new Error("unknown: host did not return task identity");
      await save(journal);
    }
    const viewed = await tools[names.automation]({
      mode: "view",
      id: journal.taskId,
    });
    if (viewed?.isError) throw new Error("Native view rejected task identity");
    let task = await readHostDefinition(journal.taskId);
    if (alreadyInstalled && input.update === true) {
      const effort = task.reasoningEffort ?? task.reasoning_effort;
      if (task.status !== "PAUSED")
        throw new Error(
          "Pause the current host before an explicit package update",
        );
      if (
        task.rrule !== expected.rrule ||
        task.model !== expected.model ||
        effort !== expected.reasoningEffort
      )
        throw new Error(
          "Read the current host schedule/model before maintenance; preserve its settings",
        );
      expected.name = task.name ?? expected.name;
      journal.updatePending = true;
      await save(journal);
      await call(names.automation, {
        mode: "update",
        id: journal.taskId,
        ...expected,
      });
      task = await readHostDefinition(journal.taskId);
    }
    if (input.projectId === null && task.target?.type !== "projectless")
      throw new Error("Host projectless target unverified");
    const val = (camel, snake) => task[camel] ?? task[snake];
    const expectedStatus =
      input.update === true
        ? "PAUSED"
        : journal.hostSnapshot?.state === "enabled"
          ? "ACTIVE"
          : "PAUSED";
    if (
      task.kind !== "cron" ||
      task.status !== expectedStatus ||
      task.rrule !== expected.rrule ||
      task.model !== expected.model ||
      task.prompt !== input.prompt ||
      val("executionEnvironment", "execution_environment") !== "local" ||
      val("reasoningEffort", "reasoning_effort") !== expected.reasoningEffort ||
      (val("projectId", "project_id") &&
        val("projectId", "project_id") !== expected.projectId) ||
      val("notificationPolicy", "notification_policy") !== "failed_runs_only"
    )
      throw new Error(
        "Host readback differs; keep paused and compare exact fields",
      );
    journal.createPending = false;
    journal.updatePending = false;
    journal.hostSnapshot = {
      host: "codex",
      platform: "macos",
      taskId: journal.taskId,
      projectRef: input.projectId ?? "projectless",
      cron: task.rrule,
      timezone: input.timezone,
      model: task.model,
      reasoningEffort: expected.reasoningEffort,
      state: task.status === "ACTIVE" ? "enabled" : "paused",
      verifiedAt: now(),
    };
    await save(journal);
    return journal.hostSnapshot;
  }
  function requireHandoff(input, journal) {
    const handoff = input.handoff;
    if (
      !handoff ||
      !["legacy_paused", "old_device_retired", "no_legacy_tasks"].includes(
        handoff.kind,
      ) ||
      handoff.acknowledged !== true ||
      !/^[a-f0-9]{64}$/.test(handoff.proofHash) ||
      !Number.isFinite(Date.parse(handoff.confirmedAt))
    )
      throw new Error(
        "Assignment readiness requires explicit legacy-task handoff evidence",
      );
    if (
      journal.workflowId !== input.workflowId ||
      journal.createPending ||
      journal.updatePending ||
      !journal.hostSnapshot
    )
      throw new Error(
        "New host installation readback required before activation",
      );
  }
  async function setHostState(input, journal, state, save) {
    if (!["paused", "enabled"].includes(state))
      throw new Error("Unsupported host state");
    if (state === "enabled") {
      requireHandoff(input, journal);
      const current = compatible(
        await mcp("get_enterprise_workflow", {
          enterpriseKey: input.enterpriseKey,
          workflowType: input.workflowType,
        }),
      );
      if (
        current.workflowId !== input.workflowId ||
        current.controlState !== "active" ||
        current.assignedInstallationId !== input.installationId
      )
        throw new Error(
          "Central assignment/control does not permit host activation",
        );
      const status = await mcp("get_workflow_status", {
        workflowId: input.workflowId,
        limit: 100,
      });
      const installation = status.installations.find(
        (i) => i.installationId === input.installationId,
      );
      if (installation?.state !== "enabled")
        throw new Error(
          "Installation must be ready/enabled centrally before host activation",
        );
    }
    const old = await readHostDefinition(journal.taskId);
    if (old.kind !== "cron" || old.execution_environment !== "local")
      throw new Error("Unsupported host task");
    await call(names.automation, {
      mode: "update",
      id: journal.taskId,
      kind: "cron",
      destination: "local",
      executionEnvironment: "local",
      name: old.name,
      prompt: old.prompt,
      rrule: old.rrule,
      model: old.model,
      reasoningEffort: old.reasoning_effort,
      projectId: old.target?.type === "projectless" ? null : input.projectId,
      notificationPolicy: "failed_runs_only",
      status: state === "enabled" ? "ACTIVE" : "PAUSED",
    });
    const actual = await readHostDefinition(journal.taskId);
    if (
      actual.status !== (state === "enabled" ? "ACTIVE" : "PAUSED") ||
      actual.rrule !== old.rrule ||
      actual.model !== old.model ||
      actual.reasoning_effort !== old.reasoning_effort ||
      actual.notification_policy !== "failed_runs_only"
    )
      throw new Error("Host state/schedule readback differs");
    journal.hostSnapshot = {
      ...journal.hostSnapshot,
      cron: actual.rrule,
      model: actual.model,
      reasoningEffort: actual.reasoning_effort ?? actual.reasoningEffort,
      state,
      verifiedAt: now(),
    };
    await save(journal);
    await mcp("manage_workflow_installation", {
      workflowId: input.workflowId,
      operation: {
        kind: "record_host",
        installationId: input.installationId,
        hostSnapshot: journal.hostSnapshot,
      },
    });
    return journal.hostSnapshot;
  }
  async function activate(input, journal, save) {
    requireHandoff(input, journal);
    const current = compatible(
      await mcp("get_enterprise_workflow", {
        enterpriseKey: input.enterpriseKey,
        workflowType: input.workflowType,
      }),
    );
    if (
      current.workflowId !== input.workflowId ||
      current.controlState !== "active" ||
      current.assignedInstallationId !== input.installationId
    )
      throw new Error(
        "Current assignment and control permission required before activation",
      );
    const actual = await readHostDefinition(journal.taskId);
    if (
      actual.status !== "PAUSED" ||
      actual.id !== journal.hostSnapshot.taskId ||
      actual.kind !== "cron" ||
      (actual.execution_environment ?? actual.executionEnvironment) !== "local"
    )
      throw new Error(
        "Actual PAUSED host readback required before any central activation",
      );
    journal.hostSnapshot = {
      ...journal.hostSnapshot,
      cron: actual.rrule,
      model: actual.model,
      reasoningEffort: actual.reasoning_effort ?? actual.reasoningEffort,
      state: "paused",
      verifiedAt: now(),
    };
    await mcp("manage_workflow_installation", {
      workflowId: input.workflowId,
      operation: {
        kind: "record_host",
        installationId: input.installationId,
        hostSnapshot: journal.hostSnapshot,
      },
    });
    await save(journal);
    const status = await mcp("get_workflow_status", {
      workflowId: input.workflowId,
      limit: 100,
    });
    const installation = status.installations.find(
      (item) => item.installationId === input.installationId,
    );
    if (!installation) throw new Error("Installation registration unavailable");
    const checks = [
      ...(installation.readinessChecks ?? []).filter(
        (check) => check.capability !== "assignment",
      ),
      {
        capability: "assignment",
        status: "ready",
        nextStep: "",
        checkedAt: now(),
      },
    ];
    const checked = await mcp("manage_workflow_installation", {
      workflowId: input.workflowId,
      operation: {
        kind: "record_checks",
        installationId: input.installationId,
        checks,
        firstRunVerification: "not_run",
      },
    });
    await mcp("manage_workflow_installation", {
      workflowId: input.workflowId,
      operation: {
        kind: "set_state",
        installationId: input.installationId,
        expectedVersion: checked.version,
        state: "enabled",
        reason: "Explicit handoff confirmed after actual paused-host readback",
      },
    });
    journal.handoff = input.handoff;
    await save(journal);
    return setHostState(input, journal, "enabled", save);
  }
  function compatible(data) {
    const c = data.capability;
    if (
      c?.id !== "enterprise-workflows-v1" ||
      c.version !== "1.0.0" ||
      c.configurationSchemaVersion !== 1 ||
      c.minimumLauncherVersion !== "0.16.0"
    )
      throw new Error("WORKFLOW_VERSION_INCOMPATIBLE");
    return data;
  }
  async function ensureRunReadiness(input) {
    const { workflowType, packageVersion } = input;
    if (!packageVersion) throw new Error("Readiness package binding required");
    const required = [
      "configuration", "permissions", "workspace", "dependencies",
      "host_schedule", "host_timezone", "host_model",
    ];
    if (workflowType === "meituan-review-operations") required.push("meituan_reviews");
    else if (workflowType === "meituan-daily-ingestion") required.push("download", "meituan_erp");
    else if (workflowType === "weekly-business-report") required.push("download");
    else throw new Error("Unknown workflow type");

    await ensureReadiness(input, required);
  }
  async function ensureReadiness(input, required) {
    const { workflowId, installationId, workflowType, packageVersion, refreshChecks } = input;
    const status = await mcp("get_workflow_status", { workflowId, limit: 1 });
    if (
      status.workflowId !== workflowId ||
      status.workflowType !== workflowType ||
      status.assignedInstallationId !== installationId ||
      status.controlState !== "active"
    )
      throw new Error("Readiness workflow binding mismatch");
    const installation = status.installations?.find(
      (item) => item.installationId === installationId,
    );
    if (installation?.state !== "enabled" || !installation.hostSnapshot)
      throw new Error("Enabled installation with recorded host required");
    if (packageVersion && installation.workflowPackageVersion !== packageVersion)
      throw new Error("Readiness package binding mismatch");

    const observedAt = Date.parse(status.observedAt);
    if (!Number.isFinite(observedAt)) throw new Error("Central readiness clock unavailable");
    const prior = new Map(
      (installation.readinessChecks ?? []).map((check) => [check.capability, check]),
    );
    const recent = (check, at) => {
      const checkedAt = Date.parse(check?.checkedAt);
      return checkedAt > at - 86400000 && checkedAt <= at + 60000;
    };
    const requiredRefresh = required.filter((name) => {
      const check = prior.get(name);
      return check?.status !== "ready" || !recent(check, observedAt);
    });
    if (!requiredRefresh.length) return false;

    function needsRefresh(capabilities) {
      const error = new Error("WORKFLOW_READINESS_REFRESH_REQUIRED: " + capabilities.join(", "));
      error.code = "WORKFLOW_READINESS_REFRESH_REQUIRED";
      error.capabilities = capabilities;
      return error;
    }
    if (typeof refreshChecks !== "function") throw needsRefresh(requiredRefresh);
    const refreshed = await refreshChecks([...requiredRefresh]);
    const checkedNow = Date.now();
    if (
      !Array.isArray(refreshed) ||
      refreshed.length !== requiredRefresh.length ||
      new Set(refreshed.map((check) => check.capability)).size !== refreshed.length ||
      refreshed.some((check) =>
        !requiredRefresh.includes(check.capability) ||
        !recent(check, checkedNow) ||
        Date.parse(check.checkedAt) <= (Date.parse(prior.get(check.capability)?.checkedAt) || 0)
      )
    )
      throw new Error("Expected fresh results for each requested readiness check");

    for (const check of refreshed) prior.set(check.capability, check);
    const saved = await mcp("manage_workflow_installation", {
      workflowId,
      operation: {
        kind: "record_checks",
        installationId,
        checks: [...prior.values()],
        firstRunVerification: installation.firstRunVerification,
      },
    });
    if (saved.installationId !== installationId)
      throw new Error("Readiness record acknowledgement mismatch");
    const savedChecks = new Map(
      (saved.readinessChecks ?? []).map((check) => [check.capability, check]),
    );
    const unavailable = required.filter((name) => {
      const check = savedChecks.get(name);
      return check?.status !== "ready" || !recent(check, Date.now());
    });
    if (unavailable.length) throw needsRefresh(unavailable);
    return true;
  }
  async function openRun(input) {
    const current = await mcp("get_enterprise_workflow", {
      enterpriseKey: input.enterpriseKey,
      workflowType: input.workflowType,
    });
    compatible(current);
    if (
      current.controlState !== "active" ||
      current.assignedInstallationId !== input.installationId
    )
      throw new Error("Workflow paused or assigned elsewhere");
    if (
      input.resume?.workflowId &&
      input.resume.workflowId !== current.workflowId
    )
      throw new Error("Resume workflow binding mismatch");
    if (!input.resume) await ensureRunReadiness({ ...input, workflowId: current.workflowId });
    const operation = input.resume
      ? {
          kind: "resume",
          runId: input.resume.runId,
          installationId: input.installationId,
          assignmentEpoch: current.assignmentEpoch,
          controlVersion: current.controlVersion,
        }
      : {
          kind: "start",
          installationId: input.installationId,
          assignmentEpoch: current.assignmentEpoch,
          expectedConfigurationVersion: current.version,
          expectedIntegrationVersion: current.integration.version,
          expectedControlVersion: current.controlVersion,
          workflowPackageVersion: input.packageVersion,
          window: input.window,
          mode: input.backfill ? "backfill" : "scheduled",
          ...(input.backfill
            ? { backfillConfirmationDigest: input.backfill.confirmationDigest }
            : {}),
        };
    const run = await mcp("manage_workflow_run", {
      workflowId: current.workflowId,
      operation,
    });
    if (
      !run.snapshot ||
      run.snapshot.workflowType !== input.workflowType ||
      !run.runId ||
      (input.resume && run.runId !== input.resume.runId)
    )
      throw new Error("Run snapshot unavailable");
    return {
      ...run,
      workflowId: current.workflowId,
      installationId: input.installationId,
      assignmentEpoch: current.assignmentEpoch,
      controlVersion: current.controlVersion,
    };
  }
  // A missing local checkpoint is not evidence that the central run is new.
  async function recoverRun(input) {
    const current = compatible(
      await mcp("get_enterprise_workflow", {
        enterpriseKey: input.enterpriseKey,
        workflowType: input.workflowType,
      }),
    );
    if (current.workflowId !== input.workflowId)
      throw new Error("Workflow binding mismatch");
    if (
      current.controlState !== "active" ||
      current.assignedInstallationId !== input.installationId
    )
      throw new Error("Workflow paused or assigned elsewhere");
    const unfinished = [],
      seen = new Set();
    let cursor, latestForWindow;
    do {
      const page = await mcp("get_workflow_status", {
        workflowId: input.workflowId,
        limit: 100,
        ...(cursor ? { cursor } : {}),
      });
      if (page.workflowId !== input.workflowId)
        throw new Error("Status workflow binding mismatch");
      for (const run of page.runs ?? []) {
        if (!run.finishedAt) unfinished.push(run);
        if (
          !latestForWindow &&
          input.window &&
          run.snapshot?.workflowType === input.workflowType &&
          run.snapshot.window.startDate === input.window.startDate &&
          run.snapshot.window.endDate === input.window.endDate &&
          Number.isInteger(current.version) &&
          Number.isInteger(current.integration?.version) &&
          run.snapshot.configurationVersion === current.version &&
          run.snapshot.integrationVersion === current.integration.version
        )
          latestForWindow = run;
      }
      cursor = page.nextCursor;
      if (cursor && seen.has(cursor))
        throw new Error("Run pagination did not advance");
      if (cursor) seen.add(cursor);
    } while (cursor);
    if (unfinished.length > 1)
      throw new Error("Multiple unfinished runs require reconciliation");
    const run = unfinished[0];
    if (
      !run &&
      !input.backfill &&
      ["meituan-daily-ingestion", "weekly-business-report"].includes(
        input.workflowType,
      ) &&
      latestForWindow?.status === "succeeded" &&
      latestForWindow.finishedAt
    )
      return {
        alreadyCompleted: true,
        workflowId: input.workflowId,
        runId: latestForWindow.id,
        snapshot: latestForWindow.snapshot,
        summary: latestForWindow.summary,
        finishedAt: latestForWindow.finishedAt,
      };
    if (input.resume?.runId && run?.id !== input.resume.runId)
      throw new Error("Local run differs from current central unfinished run");
    const pinnedVersion =
      run?.workflowPackageVersion ?? run?.snapshot?.workflowPackageVersion;
    if (run && pinnedVersion && input.packageVersion !== pinnedVersion)
      throw new Error(
        "Resume requires original package version " + pinnedVersion,
      );
    return openRun({
      ...input,
      ...(run
        ? { resume: { workflowId: input.workflowId, runId: run.id } }
        : {}),
    });
  }
  async function beginGoal(input) {
    // The saved scheduled prompt must explicitly request a Goal. A skill invocation
    // alone is not user authorization to create one.
    if (input.goalRequested !== true)
      throw new Error("Explicit scheduled Goal request required");
    if (!/^[A-Za-z0-9_-]{1,64}$/.test(input.workflowId))
      throw new Error("Stable workflow ID required");
    const marker = "SMEDC workflow " + input.workflowId;
    const current = await call("get_goal", {});
    if (current.goal && current.goal.status !== "complete") {
      if (!current.goal.objective.includes(marker + ":"))
        throw new Error("A different active Goal already owns this chat");
      if (current.goal.status !== "active")
        throw new Error("Existing Goal requires user resumption");
      return current;
    }
    return call("create_goal", {
      objective:
        marker +
        ": execute the installed workflow for its frozen window, " +
        "resuming the central unfinished run if present. Complete the required source scopes, " +
        "verify SMEDC uploads/synchronization and authorized publication, verify any enabled " +
        "email delivery or an evidenced no-new-draft/already-delivered result, and finish the " +
        "central run with its actual outcome. Use the execution plan and original provider " +
        "receipts to choose remaining work. Respect live authorization and reconcile unknown actions.",
    });
  }
  async function recoverActions(session, savePage) {
    if (!session.workflowId || !session.runId || typeof savePage !== "function")
      throw new Error("Frozen run and durable recovery-page writer required");
    const summary = {
      pageCount: 0,
      actionCount: 0,
      confirmed: 0,
      unresolved: 0,
      failed: 0,
    };
    const seenCursors = new Set(),
      seenActions = new Set();
    let cursor;
    do {
      const page = await mcp("get_workflow_status", {
        workflowId: session.workflowId,
        runId: session.runId,
        limit: 100,
        ...(cursor ? { actionCursor: cursor } : {}),
      });
      if (
        page.workflowId !== session.workflowId ||
        !Array.isArray(page.runActionRefs) ||
        !Object.hasOwn(page, "nextRunActionCursor")
      )
        throw new Error(
          "Run action inventory unavailable; compatible service rollout required",
        );
      const refs = page.runActionRefs;
      if (
        refs.length > 100 ||
        refs.some(
          (ref) =>
            ref.runId !== session.runId ||
            typeof ref.actionId !== "string" ||
            seenActions.has(ref.actionId),
        )
      )
        throw new Error("Invalid or cross-run recovery index");
      for (const ref of refs) {
        if (seenActions.has(ref.actionId))
          throw new Error("Duplicate recovery action");
        seenActions.add(ref.actionId);
      }
      const result = refs.length
        ? await mcp("record_workflow_action", {
            workflowId: session.workflowId,
            operation: {
              kind: "get",
              actionIds: refs.map((ref) => ref.actionId),
            },
          })
        : { actions: [] };
      const actions = result.actions;
      if (
        !Array.isArray(actions) ||
        actions.length !== refs.length ||
        new Set(actions.map((a) => a.actionId)).size !== refs.length ||
        actions.some(
          (a) =>
            a.runId !== session.runId ||
            !refs.some((ref) => ref.actionId === a.actionId) ||
            !["intent", "confirmed", "unknown", "failed"].includes(a.state) ||
            (a.state === "confirmed" && a.receipt?.state !== "confirmed"),
        )
      )
        throw new Error("Incomplete or cross-run recovery receipts");
      const next = page.nextRunActionCursor;
      if (
        next !== null &&
        (typeof next !== "string" ||
          seenCursors.has(next) ||
          refs.at(-1)?.actionId !== next)
      )
        throw new Error("Recovery pagination did not advance");
      await savePage({
        workflowId: session.workflowId,
        runId: session.runId,
        sequence: summary.pageCount,
        observedAt: page.observedAt ?? now(),
        actions,
        nextCursor: next,
      });
      summary.pageCount++;
      summary.actionCount += actions.length;
      summary.confirmed += actions.filter(
        (a) => a.state === "confirmed",
      ).length;
      summary.unresolved += actions.filter((a) =>
        ["intent", "unknown"].includes(a.state),
      ).length;
      summary.failed += actions.filter((a) => a.state === "failed").length;
      if (next) seenCursors.add(next);
      cursor = next;
    } while (cursor);
    return summary;
  }
  async function withLease(session, meta, invoke, save = options.saveOutcome) {
    const factual =
      meta.factualReceipt === true &&
      meta.effect === "local" &&
      ["review-sync-proof", "download-proof"].includes(meta.stage);
    if (session.leaseLost && !factual)
      throw new Error(
        "Run lease was lost; resume and reconcile before new operations",
      );
    if (typeof save !== "function")
      throw new Error("Durable operation journal required before dispatch");
    const startedAt = now(),
      operationId =
        "op-" +
        Date.now().toString(36) +
        "-" +
        Math.random().toString(36).slice(2, 10);
    await save({
      operationId,
      runId: session.runId,
      meta,
      state: "started",
      startedAt,
    });
    const timers = options.timers ?? { setTimeout, clearTimeout };
    let timer,
      renewing,
      stopped = false,
      loss,
      result,
      thrown;
    const schedule = () => {
      timer = timers.setTimeout(
        () => {
          renewing = (async () => {
            try {
              await mcp("manage_workflow_run", {
                workflowId: session.workflowId,
                operation: { kind: "renew", ...bind(session) },
              });
            } catch (error) {
              loss = error;
              session.leaseLost = true;
            }
            if (!stopped && !loss) schedule();
          })();
        },
        Math.min(session.renewAfterSeconds ?? 30, 30) * 1000,
      );
    };
    if (!session.leaseLost) schedule();
    try {
      result = await invoke();
    } catch (error) {
      thrown = error;
    } finally {
      stopped = true;
      timers.clearTimeout(timer);
      if (renewing) await renewing;
    }
    const returnedError =
      result?.isError === true ||
      (result?.exit_code !== undefined && result.exit_code !== 0);
    const unfinished = Boolean(result?.session_id);
    const state =
      unfinished ||
      (loss && !factual) ||
      ((thrown || returnedError) && meta.effect === "external_write")
        ? "unknown"
        : thrown || returnedError
          ? "failed"
          : "succeeded";
    await save({
      operationId,
      runId: session.runId,
      meta,
      state,
      startedAt,
      endedAt: now(),
      result: redactJournal(result),
      ...(thrown
        ? {
            error: redactJournal({
              name: thrown.name,
              message: thrown.message,
              ...(thrown.sessionId ? { sessionId: thrown.sessionId } : {}),
              ...(thrown.toolResult ? { toolResult: thrown.toolResult } : {}),
            }),
          }
        : {}),
      ...(loss ? { leaseError: String(loss.message ?? loss) } : {}),
    });
    if (loss && !factual) {
      const error = new Error(
        "Run lease lost during operation; retained result requires reconciliation",
      );
      error.operationResult = result;
      throw error;
    }
    if (thrown) throw thrown;
    return result;
  }
  async function check(session, intent) {
    if (session.leaseLost)
      throw new Error("Run lease lost; reconcile before new actions");
    await mcp("manage_workflow_run", {
      workflowId: session.workflowId,
      operation: { kind: "renew", ...bind(session) },
    });
    return mcp("manage_workflow_run", {
      workflowId: session.workflowId,
      operation: { kind: "check_actions", ...bind(session), actions: [intent] },
    });
  }
  async function claim(session, intent) {
    await check(session, intent);
    const r = await mcp("record_workflow_action", {
      workflowId: session.workflowId,
      operation: { kind: "intent", ...bind(session), actions: [intent] },
    });
    return firstAction(r, intent.actionId);
  }
  async function record(session, receipt, resolving = false) {
    return mcp("record_workflow_action", {
      workflowId: session.workflowId,
      operation: resolving
        ? { kind: "resolve_unknown", ...bind(session), receipt }
        : { kind: "record_receipts", ...bind(session), receipts: [receipt] },
    });
  }
  function utf8(text) {
    return Array.from(
      encodeURIComponent(text).replace(/%([0-9A-F]{2})/g, (_, h) =>
        String.fromCharCode(parseInt(h, 16)),
      ),
      (c) => c.charCodeAt(0),
    );
  }
  function sha256(bytes) {
    const k = [],
      initial = [];
    let candidate = 2;
    while (k.length < 64) {
      let prime = true;
      for (let i = 2; i * i <= candidate; i++)
        if (candidate % i === 0) {
          prime = false;
          break;
        }
      if (prime) {
        if (initial.length < 8)
          initial.push(((Math.sqrt(candidate) % 1) * 4294967296) | 0);
        k.push(((Math.cbrt(candidate) % 1) * 4294967296) | 0);
      }
      candidate++;
    }
    const a = [...bytes],
      bits = a.length * 8;
    a.push(128);
    while (a.length % 64 !== 56) a.push(0);
    for (let i = 7; i >= 0; i--) a.push(Math.floor(bits / 2 ** (i * 8)) & 255);
    const h = [...initial],
      rotate = (x, n) => (x >>> n) | (x << (32 - n));
    for (let offset = 0; offset < a.length; offset += 64) {
      const w = [];
      for (let i = 0; i < 16; i++) {
        const j = offset + i * 4;
        w.push((a[j] << 24) | (a[j + 1] << 16) | (a[j + 2] << 8) | a[j + 3]);
      }
      for (let i = 16; i < 64; i++) {
        const x = w[i - 15],
          y = w[i - 2];
        w[i] =
          ((rotate(x, 7) ^ rotate(x, 18) ^ (x >>> 3)) +
            w[i - 16] +
            (rotate(y, 17) ^ rotate(y, 19) ^ (y >>> 10)) +
            w[i - 7]) |
          0;
      }
      let [a0, b, c, d, e, f, g, h0] = h;
      for (let i = 0; i < 64; i++) {
        const t1 =
          (h0 +
            (rotate(e, 6) ^ rotate(e, 11) ^ rotate(e, 25)) +
            ((e & f) ^ (~e & g)) +
            k[i] +
            w[i]) |
          0;
        const t2 =
          ((rotate(a0, 2) ^ rotate(a0, 13) ^ rotate(a0, 22)) +
            ((a0 & b) ^ (a0 & c) ^ (b & c))) |
          0;
        h0 = g;
        g = f;
        f = e;
        e = (d + t1) | 0;
        d = c;
        c = b;
        b = a0;
        a0 = (t1 + t2) | 0;
      }
      [a0, b, c, d, e, f, g, h0].forEach((v, i) => (h[i] = (h[i] + v) | 0));
    }
    return h.map((v) => (v >>> 0).toString(16).padStart(8, "0")).join("");
  }
  function bodyBytes(body) {
    if (typeof body?.content === "string") return utf8(body.content);
    const encoded = body?.base64_url_content ?? body?.data;
    if (typeof encoded !== "string") return null;
    const alphabet =
      "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let buffer = 0,
      bits = 0;
    const bytes = [];
    for (const c of encoded
      .replace(/-/g, "+")
      .replace(/_/g, "/")
      .replace(/=+$/, "")) {
      const n = alphabet.indexOf(c);
      if (n < 0) return null;
      buffer = (buffer << 6) | n;
      bits += 6;
      if (bits >= 8) {
        bits -= 8;
        bytes.push((buffer >>> bits) & 255);
      }
    }
    return bytes;
  }
  function hasArtifact(payload, hash) {
    const bytes = bodyBytes(payload?.body);
    return (
      (bytes !== null && sha256(bytes) === hash) ||
      (payload?.parts ?? []).some((p) => hasArtifact(p, hash))
    );
  }
  function attachments(payload) {
    return [
      ...(payload?.content_disposition === "attachment" || payload?.filename
        ? [payload]
        : []),
      ...(payload?.parts ?? []).flatMap(attachments),
    ];
  }
  function addresses(value) {
    if (Array.isArray(value)) return value.flatMap(addresses);
    if (value && typeof value === "object")
      return addresses(
        value.email_address ??
          value.emailAddress ??
          value.email ??
          value.address ??
          value.value ??
          "",
      );
    return [
      ...String(value ?? "").matchAll(
        /[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi,
      ),
    ].map((match) => match[0].toLowerCase());
  }
  function attachmentIdentity(part) {
    const bytes = bodyBytes(part.body);
    return {
      filename: part.filename ?? part.file_name ?? "",
      mimeType: String(
        part.mime_type ?? part.mimeType ?? part.content_type ?? "",
      )
        .split(";")[0]
        .toLowerCase(),
      size:
        part.size ??
        part.byte_size ??
        part.byteSize ??
        part.body?.size ??
        (bytes === null ? undefined : bytes.length),
      attachmentId:
        part.attachment_id ??
        part.attachmentId ??
        part.body?.attachment_id ??
        part.body?.attachmentId,
    };
  }
  async function emailReadback(intent, action, providerId, evidence = {}) {
    const read = await call(names.read, {
      message_id: providerId,
      max_messages: 20,
    });
    const messages = Array.isArray(read)
      ? read
      : (read.messages ??
        read.thread?.messages ??
        read.emails ??
        read.thread?.emails ??
        (read.message
          ? [read.message]
          : (read.id ?? read.message_id) === providerId
            ? [read]
            : []));
    const message = messages.find(
      (item) => (item.id ?? item.message_id) === providerId,
    );
    if (!message) return null;
    const mime =
      message.payload ?? message.api_content?.payload ?? message.api_content;
    const headers = Object.fromEntries(
      (mime?.headers ?? message.headers ?? []).map((header) => [
        header.name.toLowerCase(),
        header.value,
      ]),
    );
    const header = (name, alias) => headers[name] ?? message[alias];
    const sender = addresses(header("from", "from")),
      recipients = addresses(header("to", "to")).sort();
    const expected = [...intent.identity.recipients]
      .map((value) => value.toLowerCase())
      .sort();
    const labels = (
      message.label_ids ??
      message.labelIds ??
      message.labels ??
      []
    ).map((value) => String(value.id ?? value.name ?? value).toUpperCase());
    const clearReceipt = evidence.clearSendReceiptId === providerId;
    if (labels.includes("DRAFT") && !labels.includes("SENT")) return null;
    const sentObserved =
      labels.includes("SENT") ||
      evidence.sentSearchVerified === true ||
      (clearReceipt && !labels.includes("DRAFT"));
    const subject = String(header("subject", "subject") ?? "");
    if (
      !sentObserved ||
      JSON.stringify(sender) !==
        JSON.stringify([intent.identity.sender.toLowerCase()]) ||
      JSON.stringify(recipients) !== JSON.stringify(expected) ||
      addresses(header("cc", "cc")).length ||
      addresses(header("bcc", "bcc")).length ||
      !subject.includes(intent.correlationMarker) ||
      (evidence.subject && subject !== evidence.subject)
    )
      return null;
    const actualParts = Array.isArray(message.attachments)
      ? message.attachments
      : attachments(mime);
    const actualAttachments = actualParts.map(attachmentIdentity);
    const expectedAttachments = attachments(evidence.outgoingPayload).map(
      attachmentIdentity,
    );
    const attachmentMatch =
      clearReceipt &&
      actualAttachments.length === expectedAttachments.length &&
      expectedAttachments.every((wanted) => {
        const matches = actualAttachments.filter(
          (actual) => actual.filename === wanted.filename,
        );
        if (matches.length !== 1) return false;
        const actual = matches[0];
        return (
          (!actual.mimeType || actual.mimeType === wanted.mimeType) &&
          (actual.size === undefined ||
            Number(actual.size) === Number(wanted.size)) &&
          (actual.size !== undefined || Boolean(actual.attachmentId))
        );
      });
    const candidates = [mime, { body: message.body }];
    if (typeof message.body === "string")
      candidates.push({ body: { content: message.body } });
    if (typeof message.body_html === "string")
      candidates.push({ body: { content: message.body_html } });
    const providerBytesVerified = candidates.some((payload) =>
      hasArtifact(payload, intent.artifactHash),
    );
    // A definite native send response binds the known outgoing bytes to this exact provider id.
    // Unknown recovery needs independently retrievable artifact bytes; metadata alone cannot resolve it.
    if (!providerBytesVerified && !(clearReceipt && attachmentMatch))
      return null;
    const time = now();
    if (typeof options.saveOutcome === "function")
      await options.saveOutcome({
        operationId:
          "gmail-evidence-" +
          Date.now().toString(36) +
          "-" +
          Math.random().toString(36).slice(2, 10),
        meta: {
          stage: "gmail_provider_evidence",
          effect: "read",
          actionId: intent.actionId,
        },
        state: "succeeded",
        endedAt: time,
        result: {
          providerId,
          sender,
          recipients,
          subject,
          attachments: actualAttachments,
          outgoingArtifactHash: intent.artifactHash,
          providerBytesVerified,
          verificationMode: clearReceipt
            ? "clear_send_receipt"
            : "independent_sent_readback",
        },
      });
    return {
      actionId: intent.actionId,
      state: "confirmed",
      evidence: "provider_readback",
      receiptId: providerId,
      resultHash: intent.artifactHash,
      verifiedAt: time,
      providerReadback: {
        identityHash: action.identityHash,
        artifactHash: intent.artifactHash,
        correlationMarker: intent.correlationMarker,
        providerReceiptId: providerId,
        observedAt: time,
        outcome: "sent",
      },
    };
  }
  async function sendEmail(session, intent, mail) {
    if (
      intent.identity.kind !== "email" ||
      !intent.artifactHash ||
      !intent.correlationMarker
    )
      throw new Error(
        "Email requires frozen identity, artifact hash and marker",
      );
    if (
      mail.artifactHash !== intent.artifactHash ||
      mail.cc ||
      mail.bcc ||
      !mail.payload
    )
      throw new Error("Frozen artifact mismatch or forbidden recipients");
    await check(session, intent);
    if (typeof mail.subject !== "string" || /[\r\n]/.test(mail.subject))
      throw new Error("Invalid mail subject");
    if (!hasArtifact(mail.payload, intent.artifactHash))
      throw new Error("Frozen MIME artifact differs");
    if (intent.identity.purpose === "weekly_report") {
      const attached = attachments(mail.payload);
      if (
        attached.length !== 1 ||
        !/\.html$/i.test(attached[0].filename ?? "") ||
        !hasArtifact(attached[0], intent.artifactHash)
      )
        throw new Error(
          "Weekly mail requires only the verified final HTML attachment",
        );
    }
    const profile = await call(names.profile, {});
    if (
      (
        profile.email_address ??
        profile.emailAddress ??
        profile.email
      )?.toLowerCase() !== intent.identity.sender.toLowerCase()
    )
      throw new Error(
        "needs_login: Gmail sender differs from configured account",
      );
    const identityCheckedAt = now();
    let action;
    try {
      action = await claim(session, intent);
    } catch (error) {
      // SMEDC rejects stale mail readiness before creating an intent.
      // Refresh the two read-only checks before retrying that exact claim once.
      if (error.code !== "WORKFLOW_SOURCE_UNAVAILABLE") throw error;
      const workflowType = intent.identity.purpose === "weekly_report"
        ? "weekly-business-report"
        : "meituan-review-operations";
      const refreshed = await ensureReadiness({
        workflowId: session.workflowId,
        installationId: session.installationId,
        workflowType,
        packageVersion: session.snapshot?.workflowPackageVersion,
        refreshChecks: async (capabilities) => {
          const checks = [];
          if (capabilities.includes("email_identity")) {
            checks.push({ capability: "email_identity", status: "ready", checkedAt: identityCheckedAt,
              nextStep: "Gmail account matches the authorized sender" });
          }
          if (capabilities.includes("sent_mail_lookup")) {
            const result = await call(names.search, { query: "in:sent", max_results: 1 });
            if (!Array.isArray(result.message_ids ?? result.messageIds ?? result.messages ?? result.ids))
              throw new Error("Gmail sent-mail search returned no verifiable result");
            checks.push({ capability: "sent_mail_lookup", status: "ready", checkedAt: now(),
              nextStep: "Gmail sent-mail search verified" });
          }
          return checks;
        },
      }, ["email_identity", "sent_mail_lookup"]);
      if (!refreshed) throw error;
      action = await claim(session, intent);
    }
    if (!action.permitted) {
      const partialOverlap =
        action.claimedItems !== undefined &&
        action.requestedItems !== undefined &&
        action.claimedItems < action.requestedItems;
      return {
        state: partialOverlap ? "unknown" : action.state,
        reconcile: true,
        partialOverlap,
        action,
      };
    }
    // Recheck current control immediately before the external action, after durable intent.
    await check(session, intent);
    let sent;
    try {
      sent = await withLease(
        session,
        {
          stage: "gmail_send",
          effect: "external_write",
          actionId: intent.actionId,
        },
        () =>
          call(names.send, {
            to: intent.identity.recipients.join(", "),
            from_address: intent.identity.sender,
            subject: mail.subject + " [" + intent.correlationMarker + "]",
            payload: mail.payload,
            response_fields: ["id", "thread_id"],
          }),
      );
    } catch (error) {
      await record(session, {
        actionId: intent.actionId,
        state: "unknown",
        evidence: "transport_unknown",
        reason: "Native send response uncertain; reconcile original marker",
        verifiedAt: now(),
      });
      return { state: "unknown", reconcile: true };
    }
    const providerId = sent.id ?? sent.message_id ?? sent.message?.id;
    const receipt = providerId
      ? await withLease(
          session,
          {
            stage: "gmail_readback",
            effect: "read",
            actionId: intent.actionId,
          },
          () =>
            emailReadback(intent, action, providerId, {
              clearSendReceiptId: providerId,
              outgoingPayload: mail.payload,
              subject: mail.subject + " [" + intent.correlationMarker + "]",
            }),
        )
      : null;
    if (!receipt) {
      await record(session, {
        actionId: intent.actionId,
        state: "unknown",
        evidence: "transport_unknown",
        reason: "Sent identity/attachment readback not yet verified",
        ...(providerId ? { receiptId: providerId } : {}),
        verifiedAt: now(),
      });
      return { state: "unknown", providerId, reconcile: true };
    }
    await record(session, receipt);
    return { state: "confirmed", receipt };
  }
  async function reconcileEmail(session, intent, action, continuation) {
    const originalActionId = action?.actionId ?? intent.actionId;
    const persisted = await mcp("record_workflow_action", {
      workflowId: session.workflowId,
      operation: { kind: "get", actionIds: [originalActionId] },
    });
    const stored = persisted.actions.find(
      (item) => item.actionId === originalActionId,
    );
    if (!stored) throw new Error("Original action metadata unavailable");
    if (stored.state === "confirmed")
      return { state: "confirmed", receipt: stored.receipt };
    if (!stored.artifactHash || !stored.correlationMarker)
      return { state: "unknown", needsLocalEvidence: true };
    intent = {
      actionId: stored.actionId,
      identity: stored.identity,
      artifactHash: stored.artifactHash,
      correlationMarker: stored.correlationMarker,
    };
    action = stored;
    const marker = intent.correlationMarker;
    if (!/^[A-Za-z0-9_-]+$/.test(marker))
      throw new Error("Unsafe correlation marker");
    const pageToken =
      typeof continuation === "string" ? continuation : continuation?.pageToken;
    const previous =
      typeof continuation === "object" ? (continuation.matchedIds ?? []) : [];
    const historyKnown = typeof continuation !== "string";
    const result = await call(names.search, {
      query: "in:sent subject:" + marker,
      max_results: 20,
      ...(pageToken ? { next_page_token: pageToken } : {}),
    });
    const ids =
      result.message_ids ??
      result.messageIds ??
      result.messages ??
      result.ids ??
      [];
    const receipts = [];
    for (const entry of ids) {
      const r = await emailReadback(
        intent,
        action,
        typeof entry === "string" ? entry : (entry.id ?? entry.message_id),
        { sentSearchVerified: true },
      );
      if (r) receipts.push(r);
    }
    const next = result.next_page_token ?? result.nextPageToken;
    const matchedIds = [
      ...new Set([...previous, ...receipts.map((r) => r.receiptId)]),
    ];
    if (next)
      return {
        state: "unknown",
        continuation: { pageToken: next, matchedIds },
        matched: matchedIds.length,
      };
    if (historyKnown && matchedIds.length === 1) {
      const receipt =
        receipts.find((item) => item.receiptId === matchedIds[0]) ??
        (await emailReadback(intent, action, matchedIds[0], {
          sentSearchVerified: true,
        }));
      if (receipt) {
        await record(session, receipt, true);
        return { state: "confirmed", receipt };
      }
    }
    // Zero matches is not evidence of not-executed. Duplicates/incomplete history stay unknown.
    return {
      state: "unknown",
      matched: matchedIds.length,
      needsCompleteSearch: !historyKnown,
    };
  }

  async function verifyLocalReceipt(
    session,
    intent,
    action,
    operation,
    input,
    path,
  ) {
    const metadata = await mcp("record_workflow_action", {
      workflowId: session.workflowId,
      operation: { kind: "get", actionIds: [intent.actionId] },
    });
    const persisted = metadata.actions.find(
      (item) => item.actionId === intent.actionId,
    );
    if (
      !persisted ||
      persisted.identityHash !== action.identityHash ||
      canonical(persisted.identity) !== canonical(intent.identity)
    )
      throw new Error("Original receipt intent differs");
    if (persisted.state === "confirmed") return persisted.receipt;
    action = persisted;
    await saveLocal(path, {
      ...input,
      intent,
      identityHash: action.identityHash,
    });
    const receipt = await withLease(
      session,
      {
        stage: operation,
        effect: "local",
        factualReceipt: true,
        actionId: intent.actionId,
      },
      async () => {
        const result = await runLocalCommand({
          cmd:
            quote(pythonExecutable) +
            " " +
            quote(options.localScript) +
            " " +
            operation +
            " --input " +
            quote(path),
          max_output_tokens: 30000,
        });
        if (result.exit_code !== 0)
          throw Object.assign(
            new Error("Local readback/transfer verification failed"),
            { toolResult: redactJournal(result) },
          );
        return JSON.parse(result.output);
      },
    );
    if (receipt.actionId !== intent.actionId)
      throw new Error("Local receipt action differs");
    await record(session, receipt, action.state === "unknown");
    return receipt;
  }
  async function cleanupProof(session, actionIds) {
    await mcp("manage_workflow_run", {
      workflowId: session.workflowId,
      operation: { kind: "renew", ...bind(session) },
    });
    let cursor;
    do {
      const status = await mcp("get_workflow_status", {
        workflowId: session.workflowId,
        runId: session.runId,
        limit: 100,
        ...(cursor ? { actionCursor: cursor } : {}),
      });
      if ((status.pendingActions ?? []).some((a) => a.runId === session.runId))
        throw new Error("Unknown/pending action blocks cleanup");
      cursor = status.nextActionCursor;
    } while (cursor);
    const actions = [];
    for (let i = 0; i < actionIds.length; i += 100) {
      const page = await mcp("record_workflow_action", {
        workflowId: session.workflowId,
        operation: { kind: "get", actionIds: actionIds.slice(i, i + 100) },
      });
      actions.push(...page.actions);
    }
    if (
      !actionIds.length ||
      new Set(actionIds).size !== actionIds.length ||
      actions.length !== actionIds.length ||
      actions.some(
        (a) =>
          a.runId !== session.runId ||
          a.state !== "confirmed" ||
          a.receipt?.state !== "confirmed",
      )
    )
      throw new Error("Central confirmed receipts required");
    return {
      schemaVersion: 1,
      workflowId: session.workflowId,
      runId: session.runId,
      checkedAt: now(),
      expiresAt: new Date(Date.now() + 30000).toISOString(),
      actions,
    };
  }
  async function closeRun(session, summary) {
    return mcp("manage_workflow_run", {
      workflowId: session.workflowId,
      operation: { kind: "finish", ...bind(session), summary },
    });
  }
  async function migrate(workflowId, bundle, saved, save) {
    const operate = (operation) =>
      mcp("manage_workflow_installation", { workflowId, operation });
    let state =
      saved.migration ??
      (await operate({ kind: "migration_preview", manifest: bundle.manifest }));
    saved.migration = state;
    await save(saved);
    if (state.sealedAt) return state;
    for (const page of bundle.pages) {
      state = await operate({
        kind: "migration_append",
        migrationId: state.migrationId,
        expectedVersion: state.version,
        sequence: page.sequence,
        chunk: page.chunk,
        chunkHash: page.chunkHash,
      });
      saved.migration = state;
      await save(saved);
    }
    state = await operate({
      kind: "migration_seal",
      migrationId: state.migrationId,
      expectedVersion: state.version,
      chunkCount: bundle.chunkCount,
      recordCount: bundle.recordCount,
      chunksDigest: bundle.chunksDigest,
    });
    saved.migration = state;
    await save(saved);
    return state; // User reviews returned sealed digest BEFORE validated/imported stages.
  }
  async function advanceMigration(
    workflowId,
    bundle,
    saved,
    stage,
    confirmationDigest,
    save,
  ) {
    let state = saved.migration;
    if (!state || state.confirmationDigest !== confirmationDigest)
      throw new Error("Sealed migration confirmation required");
    do {
      state = await mcp("manage_workflow_installation", {
        workflowId,
        operation: {
          kind: "migration_advance",
          migrationId: state.migrationId,
          sourceSnapshotHash: bundle.manifest.sourceSnapshotHash,
          expectedVersion: state.version,
          stage,
          confirmationDigest,
        },
      });
      saved.migration = state;
      await save(saved);
    } while (state.complete === false);
    return state;
  }
  function canonical(value) {
    if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
    if (value !== null && typeof value === "object")
      return (
        "{" +
        Object.keys(value)
          .filter((k) => value[k] !== undefined)
          .sort()
          .map((k) => JSON.stringify(k) + ":" + canonical(value[k]))
          .join(",") +
        "}"
      );
    return JSON.stringify(value);
  }
  async function verifyMigrationReadback(
    workflowId,
    bundle,
    migrationId,
    savePage,
    onMetadata,
  ) {
    let cursor,
      sequence = 0,
      count = 0,
      chain = "0".repeat(64),
      metadata;
    do {
      const page = await readMigration(workflowId, migrationId, cursor);
      metadata = page;
      if (sequence === 0 && onMetadata) await onMetadata(page);
      if (
        page.sourceSnapshotHash !== bundle.manifest.sourceSnapshotHash ||
        page.chunkCount !== bundle.chunkCount ||
        page.recordCount !== bundle.recordCount ||
        page.chunksDigest !== bundle.chunksDigest
      )
        throw new Error("Migration metadata differs from sealed source");
      for (const part of page.chunks) {
        if (part.sequence !== sequence++)
          throw new Error("Migration readback page missing or repeated");
        const hash = sha256(utf8(canonical(part.chunk)));
        const records = part.chunk.reduce(
          (n, w) =>
            n +
            w.completedActions.length +
            w.unresolved.length +
            (w.recoveryItems?.length ?? 0),
          0,
        );
        if (hash !== part.chunkHash || records > 100)
          throw new Error("Migration readback hash or bound mismatch");
        chain = sha256(utf8(canonical([chain, part.sequence, hash, records])));
        count += records;
        await savePage(part);
      }
      cursor = page.nextCursor;
    } while (cursor !== null && cursor !== undefined);
    if (
      sequence !== bundle.chunkCount ||
      count !== bundle.recordCount ||
      chain !== bundle.chunksDigest
    )
      throw new Error("Migration readback incomplete");
    return {
      verified: true,
      stage: metadata.stage,
      chunkCount: sequence,
      recordCount: count,
      chunksDigest: chain,
    };
  }
  async function restoreMachine(selector, saveState, savePage) {
    if (typeof saveState !== "function" || typeof savePage !== "function")
      throw new Error("Durable restoration callbacks required");
    const current = compatible(await mcp("get_enterprise_workflow", selector));
    const state = {
      schemaVersion: 1,
      workflowId: current.workflowId,
      enterpriseKey: current.enterpriseKey,
      workflowType: current.workflowType,
      configurationVersion: current.version,
      integrationVersion: current.integration.version,
      controlVersion: current.controlVersion,
      assignmentEpoch: current.assignmentEpoch,
      assignedInstallationId: current.assignedInstallationId,
      pendingActionCount: 0,
      pendingMetadataIncomplete: 0,
      actionPages: [],
      migrations: [],
      migrationArchives: [],
      recoveryItemCounts: { open: 0, waived: 0, resolved: 0 },
      completedActionCount: 0,
      restorationComplete: false,
      readyForActivation: false,
    };
    state.configurationRef = await savePage({
      kind: "current_configuration",
      workflowId: current.workflowId,
      data: current,
    });
    await saveState(state);
    let status = compatible(
      await mcp("get_workflow_status", {
        workflowId: current.workflowId,
        limit: 100,
      }),
    );
    if (
      !Array.isArray(status.migrations) ||
      !Array.isArray(status.pendingActions)
    )
      throw new Error("Recovery discovery capability unavailable");
    const installations = status.installations ?? [];
    const assigned = installations.find(
      (i) =>
        i.installationId === current.assignedInstallationId && i.hostSnapshot,
    );
    const latest = installations
      .filter((i) => i.hostSnapshot && i.state !== "revoked")
      .sort(
        (a, b) =>
          Date.parse(b.hostSnapshot.verifiedAt ?? 0) -
          Date.parse(a.hostSnapshot.verifiedAt ?? 0),
      )[0];
    const host = assigned ?? latest;
    if (host) {
      state.hostSnapshot = host.hostSnapshot;
      state.hostSnapshotSource = "current_installation";
    }
    const firstStatus = status,
      seenActions = new Set();
    do {
      const ids = status.pendingActions.map((a) => a.actionId);
      for (const id of ids) {
        if (seenActions.has(id))
          throw new Error("Pending action page repeated");
        seenActions.add(id);
      }
      if (ids.length) {
        const page = await mcp("record_workflow_action", {
          workflowId: current.workflowId,
          operation: { kind: "get", actionIds: ids },
        });
        if (page.actions.length !== ids.length)
          throw new Error("Original action metadata unavailable");
        const actions = page.actions.map((action) => ({
          ...action,
          originalIntent: {
            actionId: action.actionId,
            identity: action.identity,
            ...(action.artifactHash
              ? { artifactHash: action.artifactHash }
              : {}),
            ...(action.correlationMarker
              ? { correlationMarker: action.correlationMarker }
              : {}),
          },
        }));
        state.pendingActionCount += actions.filter(
          (a) => a.state === "intent" || a.state === "unknown",
        ).length;
        state.pendingMetadataIncomplete += actions.filter(
          (a) =>
            ["email", "review_publish"].includes(a.identity.kind) &&
            (!a.artifactHash || !a.correlationMarker),
        ).length;
        state.actionPages.push(
          await savePage({
            kind: "pending_actions",
            workflowId: current.workflowId,
            index: state.actionPages.length,
            actions,
          }),
        );
        await saveState(state);
      }
      if (!status.nextActionCursor) break;
      status = compatible(
        await mcp("get_workflow_status", {
          workflowId: current.workflowId,
          limit: 100,
          actionCursor: status.nextActionCursor,
        }),
      );
    } while (true);
    status = firstStatus;
    const seenMigrations = new Set();
    do {
      for (const migration of status.migrations) {
        if (
          seenMigrations.has(migration.migrationId) ||
          !migration.workflowIds.includes(current.workflowId)
        )
          throw new Error("Invalid migration discovery membership/page");
        seenMigrations.add(migration.migrationId);
        state.migrations.push(migration);
      }
      if (!status.nextMigrationCursor) break;
      status = compatible(
        await mcp("get_workflow_status", {
          workflowId: current.workflowId,
          limit: 100,
          migrationCursor: status.nextMigrationCursor,
        }),
      );
    } while (true);
    state.migrations.sort(
      (a, b) =>
        b.targetVersion - a.targetVersion ||
        Date.parse(b.createdAt) - Date.parse(a.createdAt),
    );
    const recoveredIds = new Set(),
      completedIds = new Set();
    for (const migration of state.migrations.filter((m) =>
      ["imported", "host_switched", "verified"].includes(m.stage),
    )) {
      const archive = {
        migrationId: migration.migrationId,
        pageCount: 0,
        recordCount: migration.recordCount,
        chunksDigest: migration.chunksDigest,
      };
      const verified = await verifyMigrationReadback(
        current.workflowId,
        {
          manifest: { sourceSnapshotHash: migration.sourceSnapshotHash },
          chunkCount: migration.chunkCount,
          recordCount: migration.recordCount,
          chunksDigest: migration.chunksDigest,
        },
        migration.migrationId,
        async (part) => {
          const ref = await savePage({
            kind: "migration_chunk",
            workflowId: current.workflowId,
            migrationId: migration.migrationId,
            ...part,
          });
          archive.firstPageRef ??= ref;
          archive.pageCount++;
          for (const item of part.chunk.filter(
            (w) => w.workflowId === current.workflowId,
          )) {
            for (const complete of item.completedActions) {
              if (!completedIds.has(complete.intent.actionId)) {
                completedIds.add(complete.intent.actionId);
                state.completedActionCount++;
              }
            }
            for (const recovery of item.recoveryItems ?? []) {
              if (!recoveredIds.has(recovery.itemId)) {
                recoveredIds.add(recovery.itemId);
                state.recoveryItemCounts[recovery.disposition]++;
              }
            }
          }
          await saveState(state);
        },
        async (metadata) => {
          const snapshot = metadata.manifest.workflows.find(
            (w) => w.workflowId === current.workflowId,
          );
          if (!snapshot) throw new Error("Migration omitted selected workflow");
          if (!state.hostSnapshot) {
            state.hostSnapshot = snapshot.hostSnapshot;
            state.hostSnapshotSource = "historical_migration";
          }
        },
      );
      archive.verified = verified.verified;
      state.migrationArchives.push(archive);
      await saveState(state);
    }
    state.restorationComplete = true;
    await saveState(state);
    return state; // Configuration/migration recovery never enables a host or replays an action.
  }
  async function readMigration(workflowId, migrationId, cursor) {
    return mcp("manage_workflow_installation", {
      workflowId,
      operation: {
        kind: "migration_get",
        migrationId,
        limit: 1,
        ...(cursor ? { cursor } : {}),
      },
    });
  }
  return {
    unwrap,
    saveLocal,
    prepareWorkspace,
    readHost: readHostDefinition,
    install,
    setHostState,
    activate,
    ensureRunReadiness,
    openRun,
    recoverRun,
    beginGoal,
    recoverActions,
    withLease,
    check,
    claim,
    record,
    sendEmail,
    reconcileEmail,
    closeRun,
    cleanupProof,
    migrate,
    advanceMigration,
    readMigration,
    verifyMigrationReadback,
    restoreMachine,
    confirmReviewSync: (session, intent, action, paths) =>
      verifyLocalReceipt(
        session,
        intent,
        action,
        "review-sync-proof",
        { planPath: paths.planPath, readbackPaths: paths.readbackPaths },
        paths.proofInputPath,
      ),
    confirmDownload: (session, intent, action, input) =>
      verifyLocalReceipt(
        session,
        intent,
        action,
        "download-proof",
        {
          response: input.response,
          launcherVersion: input.launcherVersion,
          ...(input.requestId ? { requestId: input.requestId } : {}),
        },
        input.proofInputPath,
      ),
    getWorkflow: async (selector) =>
      compatible(await mcp("get_enterprise_workflow", selector)),
    discover: async (input) =>
      compatible(await mcp("list_enterprise_workflows", input)),
    installation: (workflowId, operation) =>
      mcp("manage_workflow_installation", { workflowId, operation }),
    status: (input) => mcp("get_workflow_status", input),
    archive: (input) => call(names.archive, { ...input, archived: true }),
    gmailIdentity: () => call(names.profile, {}),
  };
});
