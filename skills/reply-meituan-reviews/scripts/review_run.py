#!/usr/bin/env python3
"""Local-only review parsing, checkpoints, workbook checks and guarded files.

No browser, mail, MCP, scheduler or credential access. Paths are explicit.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile

TZ = dt.timezone(dt.timedelta(hours=8))
HEADERS = [
    "客户名字",
    "客户原评价",
    "拟回复内容",
    "用户评分",
    "评价日期",
    "门店名称",
    "企业名称",
    "渠道",
    "回复状态",
]
STATES = {
    "已回复",
    "新生成待审核",
    "未回复无正文",
    "未回复有正文（仅采集）",
    "已回复待核对",
    "待核对",
}
GATES = [
    "collectionComplete",
    "identitiesVerified",
    "publicationVerified",
    "syncReadbackVerified",
    "notificationsVerified",
    "noUnresolvedErrors",
    "archiveVerified",
]


def read(p):
    return json.loads(Path(p).read_text())


def write(p, data):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + p.name, dir=p.parent)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def stamp():
    return dt.datetime.now(TZ).isoformat()


def regular(p):
    p = Path(os.path.abspath(p))
    if any(x.is_symlink() for x in [p, *p.parents]):
        raise ValueError("Symlink paths are forbidden")
    if not stat.S_ISREG(p.stat().st_mode):
        raise ValueError("Expected ordinary file")
    return p


def sha(p):
    with regular(p).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def snapshot(p):
    p = regular(p)
    s = p.stat()
    result = dict(
        path=str(p),
        size=s.st_size,
        device=s.st_dev,
        inode=s.st_ino,
        mtimeNs=s.st_mtime_ns,
        sha256=sha(p),
    )
    after = p.stat()
    if (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise ValueError("File changed during hashing")
    return result


def run_info(directory):
    directory = Path(directory).absolute()
    r = read(directory / "run.json")
    if r["runId"] != directory.name:
        raise ValueError("runId must equal run directory name")
    dt.date.fromisoformat(r["startDate"])
    dt.date.fromisoformat(r["endDate"])
    if r["startDate"] > r["endDate"]:
        raise ValueError("Invalid date range")
    return directory, r


def number(v):
    if isinstance(v, bool):
        raise ValueError("Boolean score")
    if isinstance(v, str):
        m = re.fullmatch(r"\s*([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*(?:星|分|心)?\s*", v)
        if not m:
            raise ValueError("Ambiguous score")
        v = float(m[1])
    if not isinstance(v, (float, int)) or not math.isfinite(v):
        raise ValueError("Missing/non-finite score")
    return int(v) if int(v) == v else v


def source_key(source):
    return (
        source["product"],
        source["accountRef"],
        source["channel"],
        (
            ("id", source["sourceStoreId"])
            if source.get("sourceStoreId")
            else ("name", source["sourceStoreName"])
        ),
    )


def parse_exports(a):
    import openpyxl

    directory, run = run_info(a.run_dir)
    task, records, errors, provenance = read(a.task), [], [], []
    mapping = {}
    for m in [] if task.get("sourceIdentityMappings") is not None else task["mappings"]:
        for name in [
            m["targetStoreName"],
            *[s["storeName"] for s in m["sourceStores"]],
        ]:
            if name in mapping and mapping[name] != m["targetStoreName"]:
                raise ValueError("Ambiguous mapping")
            mapping[name] = m["targetStoreName"]
    ignored = {
        (x["poiId"], x["source"], x["feedbackId"])
        for x in task.get("ignoredRecords", [])
    }
    ignored_scoped = {
        (source_key(x["source"]), x["feedbackId"])
        for x in task.get("ignoredReviewIdentities", [])
    }
    seen = set()
    for ex in read(directory / "exports.json"):
        p = regular(ex["path"])
        if task.get("sourceIdentityMappings") is not None:
            identity = ex.get("sourceIdentity")
            expected = {
                source_key(m["source"]): m["storeName"]
                for m in task["sourceIdentityMappings"]
            }
            if (
                not identity
                or identity.get("product") != "meituan_reviews"
                or expected.get(source_key(identity)) != ex["storeName"]
                or identity["sourceStoreName"] != ex["sourceStoreName"]
                or {"meituan": "美团评价", "dianping": "点评评价"}.get(
                    identity["channel"]
                )
                != ex["source"]
                or (
                    identity.get("sourceStoreId")
                    and identity["sourceStoreId"] != ex["poiId"]
                )
            ):
                raise ValueError("Unverified export namespace/source identity")
        elif mapping.get(ex["sourceStoreName"]) != ex["storeName"] or ex[
            "source"
        ] not in ["美团评价", "点评评价"]:
            raise ValueError("Unverified export scope")
        book = openpyxl.load_workbook(p, read_only=True, data_only=False)
        try:
            ws = book.active
            ws.reset_dimensions()
            it = iter(ws.iter_rows())
            header = [c.value for c in next(it)]
            required = [
                "评价ID",
                "用户昵称",
                "评分",
                "评价",
                "门店",
                "评价时间",
                "评价展示平台",
                "商家回应",
                "回应&盖楼内容",
            ]
            if len(set(header)) != len(header) or any(
                k not in header for k in required
            ):
                errors.append(
                    dict(path=str(p), error="Missing/duplicate export header")
                )
                continue
            count = 0
            for line, cells in enumerate(it, 2):
                if all(c.value is None for c in cells):
                    continue
                count += 1
                x = dict.fromkeys(header)
                x.update(zip(header, [c.value for c in cells]))
                issues = []
                if any(c.data_type == "f" for c in cells):
                    issues.append("导出含公式，不能将公式当业务文本")
                r = dict(
                    enterpriseName=task["enterpriseName"],
                    sourceStoreName=ex["sourceStoreName"],
                    poiId=ex["poiId"],
                    source=ex["source"],
                    storeName=ex["storeName"],
                    reviewerName=x["用户昵称"],
                    snapshotAt=ex["snapshotAt"],
                    content=x["评价"],
                    rawReviewedAt=str(x["评价时间"]),
                    sourceFile=str(p),
                    sourceRow=line,
                    merchantReply=None,
                    scores={},
                    issues=issues,
                )
                if ex.get("sourceIdentity"):
                    r["sourceIdentity"] = ex["sourceIdentity"]
                fid = x["评价ID"]
                if (
                    isinstance(fid, int)
                    and not isinstance(fid, bool)
                    and 0 <= fid < 10**15
                ):
                    fid = str(fid)
                if not isinstance(fid, str) or not fid.strip():
                    issues.append("评价ID缺失或数字精度未确认")
                    fid = None
                r["feedbackId"] = (
                    ("feedback-" + fid.removeprefix("feedback-")) if fid else None
                )
                legacy_key = (r["poiId"], r["source"], r["feedbackId"])
                key = (
                    (source_key(r["sourceIdentity"]), r["feedbackId"])
                    if r.get("sourceIdentity")
                    else legacy_key
                )
                if key in ignored_scoped or (
                    not task.get("ignoredReviewIdentities") and legacy_key in ignored
                ):
                    continue
                if fid and key in seen:
                    issues.append("来源身份重复，须核对，不能静默合并")
                seen.add(key)
                if x["门店"] != ex["sourceStoreName"] or x["评价展示平台"] != ex[
                    "source"
                ].removesuffix("评价"):
                    issues.append("原导出门店/渠道冲突")
                if (
                    not isinstance(r["reviewerName"], str)
                    or not r["reviewerName"].strip()
                ):
                    issues.append("原昵称缺失")
                try:
                    raw = x["评价时间"]
                    if isinstance(raw, dt.datetime):
                        actual = (
                            raw.replace(tzinfo=TZ)
                            if raw.tzinfo is None
                            else raw.astimezone(TZ)
                        )
                        precision = "second"
                    else:
                        precision = (
                            "second"
                            if re.fullmatch(
                                r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", str(raw)
                            )
                            else "minute"
                        )
                        actual = dt.datetime.strptime(
                            str(raw),
                            (
                                "%Y-%m-%d %H:%M:%S"
                                if precision == "second"
                                else "%Y-%m-%d %H:%M"
                            ),
                        ).replace(tzinfo=TZ)
                    observed = dt.datetime.fromisoformat(ex["snapshotAt"])
                    if (
                        observed.tzinfo is None
                        or not run["startDate"]
                        <= actual.date().isoformat()
                        <= run["endDate"]
                        or actual > observed
                    ):
                        raise ValueError("Outside confirmed range/snapshot")
                    r.update(
                        reviewedAt=actual.isoformat(timespec="seconds"),
                        observedReviewedAt=actual.isoformat(timespec="seconds"),
                        sourcePrecision=precision,
                        dateBasis="本轮完整平台导出；未标时区按北京时间，分钟补零仅为兼容",
                    )
                except (ValueError, TypeError):
                    r["reviewedAt"] = None
                    issues.append("评价时间/精度/范围待核对")
                try:
                    r["scores"]["总评"] = number(x["评分"])
                except ValueError:
                    issues.append("总评分待核对")
                body = r["content"]
                if (
                    body is None
                    or isinstance(body, str)
                    and (
                        not body.strip()
                        or body.strip()
                        in ["此用户没有填写评价。", "此用户没有填写评价"]
                    )
                ):
                    r["content"] = None
                elif not isinstance(body, str):
                    issues.append("正文类型待核对")
                    r["content"] = str(body)
                thread = x["回应&盖楼内容"] or ""
                parts = []
                r["rawThread"], r["rawReplyStatus"] = thread, x["商家回应"]
                if not isinstance(thread, str):
                    issues.append("商家线程类型待核对")
                else:
                    marks = list(
                        re.finditer(
                            r"【(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})】([^:\n]+):",
                            thread,
                        )
                    )
                    if thread and (not marks or thread[: marks[0].start()].strip()):
                        issues.append("商家线程包装未确认")
                    for i, m in enumerate(marks):
                        msg = thread[
                            m.end() : (
                                marks[i + 1].start()
                                if i + 1 < len(marks)
                                else len(thread)
                            )
                        ]
                        if m[2] == "商家":
                            parts.append(msg.removesuffix("\n"))
                        elif m[2] not in ["顾客", r["reviewerName"]]:
                            issues.append("线程作者未确认，须只读核验")
                r["merchantReply"] = "\n\n".join(parts) if parts else None
                if (
                    x["商家回应"] == "是"
                    and r["merchantReply"]
                    and r["merchantReply"].strip()
                ):
                    r.update(replyStatus="replied", sheetStatus="已回复")
                elif x["商家回应"] == "否" and not parts:
                    r.update(
                        replyStatus=(
                            "unreplied_with_content"
                            if r["content"]
                            else "unreplied_no_content"
                        ),
                        sheetStatus=(
                            "未回复有正文（仅采集）" if r["content"] else "未回复无正文"
                        ),
                    )
                else:
                    issues.append("商家状态与完整回复待核对")
                r["whiteListed"] = r["storeName"] in task["replyWhitelist"]
                r["needsDraft"] = (
                    r["whiteListed"]
                    and r.get("replyStatus") == "unreplied_with_content"
                    and not issues
                )
                if issues or r["needsDraft"]:
                    r["sheetStatus"] = (
                        "已回复待核对" if x["商家回应"] == "是" and issues else "待核对"
                    )
                records.append(r)
            if count != ex["pageCount"]:
                errors.append(
                    dict(
                        path=str(p),
                        error="页面/导出数量不一致",
                        expected=ex["pageCount"],
                        actual=count,
                    )
                )
            provenance.append(
                dict(path=str(p), sha256=sha(p), exportRows=count, scope=ex)
            )
        finally:
            book.close()
    for row, r in enumerate(records, 2):
        r["sheetRow"] = row
    write(directory / "records.json", records)
    write(
        directory / "parse-result.json",
        dict(
            rows=len(records),
            issues=sum(bool(r["issues"]) for r in records),
            errors=errors,
            exports=provenance,
        ),
    )
    print(
        json.dumps(
            dict(
                rows=len(records),
                needsDraft=sum(r["needsDraft"] for r in records),
                issueRows=sum(bool(r["issues"]) for r in records),
                fileErrors=len(errors),
            )
        )
    )


def verify(a):
    import openpyxl

    records = read(a.records)
    book = openpyxl.load_workbook(a.workbook, data_only=False)
    try:
        if book.sheetnames != ["评价审阅表"]:
            raise ValueError("Expected one review sheet")
        ws = book.active
        if (
            ws.max_column != 9
            or ws.max_row != len(records) + 1
            or [c.value for c in ws[1]] != HEADERS
            or ws.freeze_panes != "B2"
        ):
            raise ValueError("Workbook structure mismatch")
        for i, r in enumerate(records, 2):
            if r["sheetStatus"] not in STATES:
                raise ValueError("Unknown row status")
            reply = (
                r.get("draftReply")
                if r["sheetStatus"] == "新生成待审核"
                else r.get("merchantReply") if r["sheetStatus"] == "已回复" else None
            )
            date = (
                dt.datetime.fromisoformat(r["reviewedAt"])
                .astimezone(TZ)
                .replace(tzinfo=None)
                if r.get("reviewedAt")
                else "待核对：" + (r.get("rawReviewedAt") or "来源未显示时间")
            )
            expected = [
                r["reviewerName"],
                r.get("content"),
                reply,
                r.get("scores", {}).get("总评"),
                date,
                r["storeName"],
                r["enterpriseName"],
                r["source"],
                r["sheetStatus"],
            ]
            for cell, v in zip(ws[i], expected):
                if cell.data_type == "f" or cell.value != v:
                    raise ValueError(
                        f"Row {i}, column {cell.column}: value/formula mismatch"
                    )
            c = ws.cell(i, 4)
            if c.value is not None and (
                isinstance(c.value, bool)
                or not isinstance(c.value, (int, float))
                or c.number_format != "General"
            ):
                raise ValueError("Score type/format mismatch")
            if (
                r.get("reviewedAt")
                and ws.cell(i, 5).number_format != 'yyyy-mm-dd"T"hh:mm:ss"+08:00"'
            ):
                raise ValueError("Date format mismatch")
        if records and not any(
            t.ref == f"A1:I{len(records)+1}" and t.autoFilter is not None
            for t in ws.tables.values()
        ):
            raise ValueError("Missing filter table")
        print(json.dumps(dict(verifiedRows=len(records), sha256=sha(a.workbook))))
    finally:
        book.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    for name in ["parse", "checkpoint", "archive", "manifest", "cleanup"]:
        q = sub.add_parser(name)
        q.add_argument("--run-dir", required=True)
        if name == "parse":
            q.add_argument("--task", required=True)
        if name == "checkpoint":
            q.add_argument("--observation", required=True)
        if name in ["archive", "manifest"]:
            q.add_argument("--files", nargs="+", required=True)
        if name == "archive":
            q.add_argument("--archive-dir", required=True)
        if name == "manifest":
            q.add_argument("--output", required=True)
        if name == "cleanup":
            for arg in ["manifest", "gate", "result"]:
                q.add_argument("--" + arg, required=True)
    q = sub.add_parser("verify")
    q.add_argument("--records", required=True)
    q.add_argument("--workbook", required=True)
    a = p.parse_args()
    if a.command == "parse":
        return parse_exports(a)
    if a.command == "verify":
        return verify(a)
    directory, run = run_info(a.run_dir)
    if a.command == "checkpoint":
        obs = read(a.observation)
        for key in [
            "poiId",
            "source",
            "observedAt",
            "sourceStoreName",
            "storeName",
            "pageCount",
            "stage",
        ]:
            if key not in obs:
                raise ValueError("Missing checkpoint field: " + key)
        if (
            obs["startDate"] != run["startDate"]
            or obs["endDate"] != run["endDate"]
            or isinstance(obs["pageCount"], bool)
            or not isinstance(obs["pageCount"], int)
            or obs["pageCount"] < 0
        ):
            raise ValueError("Checkpoint range/count mismatch")
        out = directory / "progress.json"
        data = read(out) if out.exists() else dict(runId=run["runId"], scopes={})
        if data["runId"] != run["runId"]:
            raise ValueError("Checkpoint run mismatch")
        data["scopes"][obs["poiId"] + "|" + obs["source"]] = obs
        data["updatedAt"] = stamp()
        write(out, data)
        print(json.dumps(dict(savedScopes=len(data["scopes"]))))
    elif a.command in ["manifest", "archive"]:
        files = [regular(f) for f in a.files]
        if len(set(files)) != len(files) or any(
            not f.is_relative_to(directory) for f in files
        ):
            raise ValueError("Files must be distinct ordinary files within this run")
        if a.command == "manifest":
            output = Path(a.output).absolute()
            if output in files:
                raise ValueError("Cannot delete manifest")
            write(
                output,
                dict(
                    runId=run["runId"],
                    createdAt=stamp(),
                    files=[snapshot(f) for f in files],
                ),
            )
        else:
            archive = Path(a.archive_dir).absolute()
            if (
                archive.is_relative_to(directory)
                or directory.is_relative_to(archive)
                or any(x.is_symlink() for x in [archive, *archive.parents])
            ):
                raise ValueError("Archive must be separate and not symlinked")
            checks = []
            for f in files:
                dest = archive / f.relative_to(directory)
                if dest.exists() or dest.is_symlink():
                    raise ValueError("Refusing to overwrite archived evidence")
                before = sha(f)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest)
                if before != sha(dest) or before != sha(f):
                    raise ValueError("Archive checksum mismatch")
                if dest.suffix == ".json":
                    read(dest)
                checks.append(dict(path=str(dest), sha256=before))
            write(
                archive / "archive-verification.json",
                dict(runId=run["runId"], checkedAt=stamp(), files=checks),
            )
        print(json.dumps(dict(registeredFiles=len(files))))
    else:
        gate, manifest = read(a.gate), read(a.manifest)
        if (
            gate.get("runId") != run["runId"]
            or manifest.get("runId") != run["runId"]
            or any(gate.get(k) is not True for k in GATES)
            or not gate.get("evidenceFiles")
        ):
            raise ValueError("Cleanup gate incomplete")
        if run.get("workflowBinding"):
            central_file = regular(gate.get("centralProofPath", ""))
            if central_file.is_relative_to(directory) or sha(central_file) != gate.get(
                "centralProofSha256"
            ):
                raise ValueError("Central proof missing/changed")
            central = read(central_file)
            actions = {x["actionId"]: x for x in central.get("actions", [])}
            action_ids = gate.get("centralActionIds", [])
            if (
                not action_ids
                or central.get("runId") != run["runId"]
                or central.get("workflowId") != run["workflowBinding"]["workflowId"]
                or dt.datetime.fromisoformat(
                    central["expiresAt"].replace("Z", "+00:00")
                )
                <= dt.datetime.now(dt.timezone.utc)
                or any(
                    actions.get(x, {}).get("state") != "confirmed"
                    or actions[x].get("receipt", {}).get("state") != "confirmed"
                    or actions[x].get("runId") != run["runId"]
                    for x in action_ids
                )
            ):
                raise ValueError(
                    "Central confirmed receipt required for workflow cleanup"
                )
        for proof in gate["evidenceFiles"]:
            ep = regular(proof["path"])
            if ep.is_relative_to(directory) or sha(ep) != proof["sha256"]:
                raise ValueError("Archive evidence missing/changed")
        owner_path = regular(gate["lockOwnerPath"])
        if read(owner_path).get("runId") != run["runId"]:
            raise ValueError("This run does not hold the lock")
        protected = {str(Path(x).absolute()) for x in [a.manifest, a.gate, a.result]}
        result = dict(
            runId=run["runId"], deleted=[], retained=[], errors=[], freedBytes=0
        )
        for index, item in enumerate(manifest["files"]):
            try:
                if read(owner_path).get("runId") != run["runId"]:
                    raise ValueError("Run lock changed")
                f = regular(item["path"])
                if (
                    not f.is_relative_to(directory)
                    or str(f) in protected
                    or snapshot(f) != item
                ):
                    raise ValueError("File outside run, protected or changed")
                f.unlink()
                result["deleted"].append(item)
                result["freedBytes"] += item["size"]
            except Exception as e:
                result["retained"].extend(manifest["files"][index:])
                result["errors"].append(dict(path=item["path"], error=str(e)))
                break
        result["status"] = "succeeded" if not result["errors"] else "stopped"
        write(a.result, result)
        print(
            json.dumps(
                dict(
                    status=result["status"],
                    deletedFiles=len(result["deleted"]),
                    freedBytes=result["freedBytes"],
                )
            )
        )


if __name__ == "__main__":
    main()
