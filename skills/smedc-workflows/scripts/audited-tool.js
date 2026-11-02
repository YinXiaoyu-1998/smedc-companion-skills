// Evaluate this function expression in functions.exec. The caller supplies its tools object.
// Records before dispatch and before returning any error. Does not retry or change the result.
(async function auditedTool(
  tools,
  logger,
  runDir,
  meta,
  invoke,
  pythonExecutable = "python3",
) {
  const quote = (value) => "'" + String(value).replace(/'/g, "'\\''") + "'";
  const command = async (args) => {
    const r = await tools.exec_command({
      cmd: [pythonExecutable, logger, ...args].map(quote).join(" "),
      max_output_tokens: 1200,
    });
    if (r.exit_code !== 0 || r.session_id)
      throw new Error("Audit persistence failed: " + r.output);
    return JSON.parse(r.output);
  };
  const begun = await command([
    "start",
    "--run-dir",
    runDir,
    "--meta-json",
    JSON.stringify(meta),
  ]);
  let result,
    thrown,
    didThrow = false;
  try {
    result = await invoke();
  } catch (error) {
    thrown = error;
    didThrow = true;
  }
  const failed =
    didThrow ||
    result?.isError === true ||
    (result?.exit_code != null && result.exit_code !== 0);
  const running = Boolean(result?.session_id);
  const payload = didThrow
    ? {
        exceptionType: thrown?.name || typeof thrown,
        message: String(thrown?.message ?? thrown),
        stack: thrown?.stack ?? null,
      }
    : failed
      ? result
      : {
          isError: false,
          exit_code: result?.exit_code ?? null,
          session_id: result?.session_id ?? null,
        };
  // Full errors are not truncated. Large payloads are stored in bounded chunks before finish.
  const redact = (value) => {
    if (Array.isArray(value)) return value.map(redact);
    if (value && typeof value === "object")
      return Object.fromEntries(
        Object.entries(value).map(([k, v]) => [
          k,
          /authorization|cookie|password|secret|access.?token|refresh.?token|api.?key/i.test(
            k,
          )
            ? "<REDACTED>"
            : redact(v),
        ]),
      );
    return typeof value === "string"
      ? value
          .replace(/\bBearer\s+[^\s"']+/gi, "Bearer <REDACTED>")
          .replace(
            /(authorization|cookie|password|access_token|refresh_token|api_key)\s*[:=]\s*[^\r\n]+/gi,
            "$1: <REDACTED>",
          )
      : value;
  };
  const encoded = JSON.stringify(redact(payload));
  let payloadArgs;
  if (encoded.length < 24000) payloadArgs = ["--payload-json", encoded];
  else {
    const file = runDir + "/call-audit/" + begun.callId + ".payload";
    for (let i = 0; i < encoded.length; i += 24000) {
      const script =
        "import pathlib,sys; p=pathlib.Path(sys.argv[1]); f=p.open(sys.argv[2],encoding='utf-8'); f.write(sys.argv[3]); f.close()";
      const r = await tools.exec_command({
        cmd: [
          pythonExecutable,
          "-c",
          script,
          file,
          i === 0 ? "x" : "a",
          encoded.slice(i, i + 24000),
        ]
          .map(quote)
          .join(" "),
        max_output_tokens: 300,
      });
      if (r.exit_code !== 0)
        throw new Error("Audit payload persistence failed: " + r.output);
    }
    payloadArgs = ["--payload-file", file];
  }
  // An error on a write does not prove that the server did not commit it.
  const status =
    running || (failed && meta.effect === "external_write")
      ? "unknown"
      : failed
        ? "failed"
        : "succeeded";
  await command([
    "finish",
    "--run-dir",
    runDir,
    "--call-id",
    begun.callId,
    "--status",
    status,
    ...payloadArgs,
  ]);
  if (didThrow) throw thrown;
  return result;
});
