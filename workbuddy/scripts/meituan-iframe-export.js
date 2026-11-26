({ frameUrl, reportSelector, controlSelector, label }, root = document) => {
  const stop = (reason) => ({ dispatched: false, reason });
  if (![frameUrl, reportSelector, controlSelector, label].every(
    (value) => typeof value === "string" && value.trim(),
  )) return stop("missing_target");

  try {
    if (new URL(frameUrl).origin !== "https://pos.meituan.com") return stop("unexpected_origin");
  } catch {
    return stop("invalid_frame_url");
  }

  const frames = [];
  function visit(doc) {
    for (const iframe of doc.querySelectorAll("iframe")) {
      const child = iframe.contentDocument;
      if (!child) continue;
      if (child.location.href === frameUrl) frames.push(child);
      visit(child);
    }
  }
  visit(root);
  if (frames.length !== 1) return stop("frame_missing_or_ambiguous");

  const frame = frames[0];
  const reports = frame.querySelectorAll(reportSelector);
  if (reports.length !== 1) return stop("report_missing_or_ambiguous");
  const controls = reports[0].querySelectorAll(controlSelector);
  if (controls.length !== 1) return stop("control_missing_or_ambiguous");

  const control = controls[0];
  const actualLabel = (control.innerText ?? control.textContent ?? "")
    .replace(/\s+/g, " ").trim() || control.getAttribute("aria-label") || control.getAttribute("title");
  const view = frame.defaultView;
  const bounds = control.getBoundingClientRect();
  if (actualLabel !== label || !control.isConnected || !view
      || control.matches(":disabled") || control.closest('[aria-disabled="true"], [inert], [hidden]')
      || bounds.width <= 0 || bounds.height <= 0 || view.getComputedStyle(control).visibility !== "visible") {
    return stop("control_changed_or_unavailable");
  }

  const eventTypes = ["pointerdown", "mousedown", "pointerup", "mouseup", "click"];
  for (const [index, type] of eventTypes.entries()) {
    control.dispatchEvent(new view.MouseEvent(type, {
      bubbles: true,
      cancelable: true,
      view,
      clientX: bounds.x + bounds.width / 2,
      clientY: bounds.y + bounds.height / 2,
      button: 0,
      buttons: index < 2 ? 1 : 0,
    }));
  }
  return { dispatched: true };
}
