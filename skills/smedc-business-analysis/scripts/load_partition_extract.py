#!/usr/bin/env python3
"""Stream launcher-managed partition CSVs into the report's aggregate job results."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from assemble_query_bundle import dump_json_exact, is_error_envelope, unwrap_success_envelope


class ExtractError(ValueError):
    pass


def load_json(path: Path, description: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
    except FileNotFoundError as exc:
        raise ExtractError(f"{description} not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ExtractError(f"{description} is not valid JSON: {path}: {exc}") from exc


def require_object(value: Any, description: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ExtractError(f"{description} must be a JSON object")
    return value


def safe_response_path(responses_dir: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute():
        raise ExtractError(f"outputFile must be relative: {relative}")
    root = responses_dir.resolve()
    result = (root / candidate).resolve()
    if result != root and root not in result.parents:
        raise ExtractError(f"outputFile escapes responses directory: {relative}")
    return result


def compact_to_iso(value: str) -> str:
    if len(value) != 8 or not value.isdigit():
        raise ExtractError(f"partition extract date must be YYYYMMDD: {value}")
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def validate_extract_directory(raw: Any) -> Path:
    if not isinstance(raw, str) or not raw:
        raise ExtractError("download response localDirectory must be a non-empty string")
    path = Path(raw)
    if path.is_symlink() or not path.is_dir():
        raise ExtractError(f"download response localDirectory is not a regular directory: {path}")
    resolved = path.resolve()
    if resolved.parent.name != "smedc-partition-extracts" or not resolved.name.startswith("extract-"):
        raise ExtractError(f"refusing non-launcher extract directory: {path}")
    return resolved


def registry_maps(registry_response: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    payload = require_object(unwrap_success_envelope(registry_response), "registry response")
    datasets = payload.get("datasets")
    if not isinstance(datasets, list):
        raise ExtractError("registry response datasets must be an array")
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for dataset in datasets:
        if not isinstance(dataset, dict) or not isinstance(dataset.get("dataset"), str) or not isinstance(dataset.get("fields"), list):
            raise ExtractError("registry response contains a malformed dataset")
        fields: dict[str, dict[str, Any]] = {}
        for item in dataset["fields"]:
            if not isinstance(item, dict) or not isinstance(item.get("canonicalName"), str) or not isinstance(item.get("sourceColumn"), str):
                raise ExtractError(f"registry dataset {dataset['dataset']} contains a malformed field")
            fields[item["canonicalName"]] = item
        result[dataset["dataset"]] = fields
    return result


def required_fields(job: dict[str, Any]) -> set[str]:
    query = job["input"]
    names = set(query.get("groupBy", []))
    filter_spec = query.get("filter")
    if isinstance(filter_spec, dict) and isinstance(filter_spec.get("field"), str):
        names.add(filter_spec["field"])
    for aggregate in query.get("aggregates", []):
        names.add(aggregate["field"])
        if isinstance(aggregate.get("weightField"), str):
            names.add(aggregate["weightField"])
    return names


def parse_cell(text: str, field_spec: dict[str, Any], row_label: str) -> Any:
    value = text.strip()
    if not value:
        return None
    field_type = field_spec.get("type")
    try:
        if field_type == "integer":
            return int(value)
        if field_type in {"decimal", "percent"}:
            return Decimal(value)
    except (ValueError, InvalidOperation) as exc:
        raise ExtractError(f"{row_label} field {field_spec['canonicalName']} is not numeric") from exc
    return value


def sort_value(value: Any) -> tuple[int, Any]:
    return (1, "") if value is None else (0, value)


@dataclass
class GroupState:
    sums: dict[str, Decimal] = field(default_factory=lambda: defaultdict(Decimal))
    weighted_numerators: dict[str, Decimal] = field(default_factory=lambda: defaultdict(Decimal))
    weighted_denominators: dict[str, Decimal] = field(default_factory=lambda: defaultdict(Decimal))


@dataclass
class JobAccumulator:
    job: dict[str, Any]
    groups: dict[tuple[Any, ...], GroupState] = field(default_factory=dict)

    def add(self, row: dict[str, Any]) -> None:
        query = self.job["input"]
        filter_spec = query.get("filter")
        if isinstance(filter_spec, dict):
            if filter_spec.get("op") != "between" or not isinstance(filter_spec.get("value"), list):
                raise ExtractError(f"local job {self.job['id']} has unsupported filter")
            value = row.get(filter_spec["field"])
            if value is None or not (filter_spec["value"][0] <= value <= filter_spec["value"][1]):
                return
        group_by = query.get("groupBy", [])
        key = tuple(row.get(name) for name in group_by)
        state = self.groups.setdefault(key, GroupState())
        for aggregate in query.get("aggregates", []):
            alias = aggregate["as"]
            value = row.get(aggregate["field"])
            if aggregate["op"] == "sum":
                if value is not None:
                    state.sums[alias] += Decimal(value)
            elif aggregate["op"] == "weightedAvg":
                weight = row.get(aggregate["weightField"])
                if value is not None and weight is not None:
                    decimal_weight = Decimal(weight)
                    state.weighted_numerators[alias] += Decimal(value) * decimal_weight
                    state.weighted_denominators[alias] += decimal_weight
            else:
                raise ExtractError(f"local job {self.job['id']} uses unsupported aggregate {aggregate['op']}")

    def rows(self) -> list[dict[str, Any]]:
        query = self.job["input"]
        group_by = query.get("groupBy", [])
        rows: list[dict[str, Any]] = []
        for key, state in self.groups.items():
            row = dict(zip(group_by, key, strict=True))
            for aggregate in query.get("aggregates", []):
                alias = aggregate["as"]
                if aggregate["op"] == "sum":
                    row[alias] = state.sums[alias]
                else:
                    denominator = state.weighted_denominators[alias]
                    row[alias] = state.weighted_numerators[alias] / denominator if denominator else None
            rows.append(row)
        for order in reversed(query.get("sort", [])):
            rows.sort(key=lambda row: sort_value(row.get(order["field"])), reverse=order.get("direction") == "desc")
        return rows


def metadata_count(value: Any, label: str) -> int:
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        return int(value)
    raise ExtractError(f"{label} must be a nonnegative integer or decimal string")


def validate_file_integrity(directory: Path, file_spec: dict[str, Any]) -> Path:
    file_name = file_spec.get("fileName")
    if not isinstance(file_name, str) or Path(file_name).name != file_name:
        raise ExtractError(f"invalid launcher partition file name: {file_name}")
    path = directory / file_name
    if path.is_symlink() or not path.is_file() or path.resolve().parent != directory:
        raise ExtractError(f"invalid launcher partition file path: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as binary:
        for chunk in iter(lambda: binary.read(1024 * 1024), b""):
            digest.update(chunk)
    if path.stat().st_size != metadata_count(file_spec.get("byteSize"), "byteSize") or digest.hexdigest() != file_spec.get("checksumSha256"):
        raise ExtractError(f"launcher partition integrity mismatch: {file_name}")
    metadata_count(file_spec.get("rowCount"), "rowCount")
    return path


def validate_download(extract_spec: dict[str, Any], response: dict[str, Any]) -> tuple[Path, list[dict[str, Any]]]:
    expected = extract_spec["input"]
    for name in ("dataset", "enterpriseName"):
        if response.get(name) != expected.get(name):
            raise ExtractError(f"extract {extract_spec['id']} response {name} mismatch")
    for name in ("startDate", "endDate"):
        if response.get(name) != compact_to_iso(expected[name]):
            raise ExtractError(f"extract {extract_spec['id']} response {name} mismatch")
    directory = validate_extract_directory(response.get("localDirectory"))
    local_manifest = require_object(load_json(directory / "manifest.json", "launcher extract manifest"), "launcher extract manifest")
    for name in ("dataset", "enterpriseName", "startDate", "endDate"):
        if local_manifest.get(name) != response.get(name):
            raise ExtractError(f"extract {extract_spec['id']} local manifest {name} mismatch")
    files = local_manifest.get("files")
    response_files = response.get("files")
    if not isinstance(files, list) or not isinstance(response_files, list):
        raise ExtractError(f"extract {extract_spec['id']} files must be arrays")
    if any(not isinstance(item, dict) for item in files) or any(not isinstance(item, str) for item in response_files):
        raise ExtractError("partition extract has malformed file metadata")
    if [item.get("fileName") for item in files] != response_files:
        raise ExtractError(f"extract {extract_spec['id']} file list mismatch")
    start, end = compact_to_iso(expected["startDate"]), compact_to_iso(expected["endDate"])
    for item in files:
        business_date = item.get("businessDate")
        if not isinstance(business_date, str) or not start <= business_date <= end:
            raise ExtractError("partition date is outside requested download range")
        fragments = expected.get("storeNameContains", [])
        if fragments and not any(fragment in str(item.get("storeName") or "") for fragment in fragments):
            raise ExtractError("partition metadata violates requested storeNameContains")
        if expected.get("storeIds") and item.get("storeId") not in expected["storeIds"]:
            raise ExtractError("partition metadata violates requested storeIds")
    for name in ("partitionCount", "totalRowCount"):
        if metadata_count(local_manifest.get(name), name) != metadata_count(response.get(name), name):
            raise ExtractError(f"extract {extract_spec['id']} local manifest {name} mismatch")
    if metadata_count(response.get("partitionCount"), "partitionCount") != len(files):
        raise ExtractError("partition count does not match files")
    if len(response_files) != len(set(response_files)):
        raise ExtractError("partition extract repeats file names")
    if metadata_count(response.get("totalRowCount"), "totalRowCount") != sum(metadata_count(item.get("rowCount"), "rowCount") for item in files):
        raise ExtractError("total row count does not match files")
    return directory, files


def process_file(
    dataset: str,
    directory: Path,
    file_spec: dict[str, Any],
    fields: dict[str, dict[str, Any]],
    accumulators: list[JobAccumulator],
    store_name_contains: list[str],
    validate_service_scope: bool = False,
) -> None:
    path = validate_file_integrity(directory, file_spec)
    file_name = file_spec["fileName"]
    if validate_service_scope and store_name_contains and not any(fragment in str(file_spec.get("storeName") or "") for fragment in store_name_contains):
        raise ExtractError(f"partition {file_name} violates requested storeNameContains")
    needed = set().union(*(required_fields(item.job) for item in accumulators))
    if store_name_contains:
        needed.add("store_name")
    source_by_canonical = {name: fields[name]["sourceColumn"] for name in needed if name in fields}
    if set(source_by_canonical) != needed:
        missing = ", ".join(sorted(needed - set(source_by_canonical)))
        raise ExtractError(f"registry dataset {dataset} is missing fields: {missing}")
    row_count = 0
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        missing_headers = [source for source in source_by_canonical.values() if source not in headers]
        if missing_headers:
            raise ExtractError(f"partition {file_name} is missing canonical headers: {', '.join(missing_headers)}")
        for index, source_row in enumerate(reader, start=2):
            row_count += 1
            row = {
                canonical: parse_cell(source_row[source], fields[canonical], f"{file_name}:{index}")
                for canonical, source in source_by_canonical.items()
            }
            if row.get("business_date") != file_spec.get("businessDate"):
                raise ExtractError(f"partition {file_name} row {index} date does not match its manifest")
            if store_name_contains and not any(fragment in str(row.get("store_name") or "") for fragment in store_name_contains):
                if validate_service_scope:
                    raise ExtractError(f"partition {file_name} row {index} violates requested storeNameContains")
                continue
            for accumulator in accumulators:
                accumulator.add(row)
    if row_count != metadata_count(file_spec.get("rowCount"), "rowCount"):
        raise ExtractError(f"partition {file_name} row count mismatch")


def materialize(manifest: dict[str, Any], registry_response: dict[str, Any], responses_dir: Path) -> None:
    from partition_download_plan import resolve_shared_report
    manifest = resolve_shared_report(manifest)
    jobs = manifest.get("jobs")
    extracts = manifest.get("extracts")
    if not isinstance(jobs, list) or not isinstance(extracts, list):
        raise ExtractError("manifest jobs and extracts must be arrays")
    report = require_object(manifest.get("report", {}), "manifest report")
    store_name_contains = report.get("storeNameContains", [])
    if not isinstance(store_name_contains, list) or any(
        not isinstance(fragment, str) or not fragment or fragment != fragment.strip()
        for fragment in store_name_contains
    ):
        raise ExtractError("manifest report storeNameContains must contain non-blank text")
    local_jobs = [job for job in jobs if isinstance(job, dict) and job.get("tool") == "local_partition_aggregate"]
    fields_by_dataset = registry_maps(registry_response)
    accumulators = {job["id"]: JobAccumulator(job) for job in local_jobs}
    seen_directories: set[Path] = set()
    seen_partitions: dict[tuple[str, str, str, str], tuple[str, int]] = {}
    for extract_spec in extracts:
        if not isinstance(extract_spec, dict) or extract_spec.get("tool") != "download_structured_partitions":
            raise ExtractError("manifest contains a malformed partition extract")
        state = extract_spec.get("downloadState", {}).get("status")
        if ("sharedDownload" in manifest and state != "succeeded") or state in {"failed", "expired", "queued", "running", "ready"}:
            raise ExtractError(f"extract {extract_spec['id']} is not a successful local download")
        if "storeNameContains" in extract_spec["input"] and set(extract_spec["input"]["storeNameContains"]) != set(store_name_contains):
            raise ExtractError("extract storeNameContains differs from report scope")
        response_path = safe_response_path(responses_dir, extract_spec["outputFile"])
        saved_response = extract_spec.get("downloadState", {}).get("response") if state == "succeeded" else None
        raw_response = saved_response if saved_response is not None else load_json(response_path, "saved partition download response")
        response = require_object(unwrap_success_envelope(raw_response), "partition download response")
        if is_error_envelope(raw_response) or is_error_envelope(response) or response.get("status") in {"failed", "expired", "queued", "running"}:
            raise ExtractError("partition download failed or is not complete")
        directory, files = validate_download(extract_spec, response)
        if directory in seen_directories:
            raise ExtractError(f"partition extract directory is reused: {directory}")
        seen_directories.add(directory)
        dataset = extract_spec["input"]["dataset"]
        dataset_accumulators = [item for item in accumulators.values() if item.job["input"]["dataset"] == dataset]
        if dataset not in fields_by_dataset or not dataset_accumulators:
            raise ExtractError(f"partition extract {extract_spec['id']} has no local jobs or registry")
        for file_spec in files:
            if not isinstance(file_spec, dict):
                raise ExtractError(f"extract {extract_spec['id']} has malformed file metadata")
            # Launcher file names carry the ID/name hash, supporting null merchant IDs.
            store_id = file_spec.get("storeId")
            store_identity = f"id:{store_id}" if isinstance(store_id, str) and store_id else file_spec.get("fileName")
            identity = (dataset, extract_spec["input"]["enterpriseName"], store_identity, file_spec.get("businessDate"))
            if any(not isinstance(value, str) or not value for value in identity):
                raise ExtractError("partition metadata is missing its store/date identity")
            checksum = file_spec.get("checksumSha256")
            if identity in seen_partitions:
                validate_file_integrity(directory, file_spec)
                if seen_partitions[identity] != (checksum, metadata_count(file_spec.get("rowCount"), "rowCount")):
                    raise ExtractError("partition identity has conflicting checksums")
                continue
            seen_partitions[identity] = (checksum, metadata_count(file_spec.get("rowCount"), "rowCount"))
            process_file(dataset, directory, file_spec, fields_by_dataset[dataset], dataset_accumulators, store_name_contains, "storeNameContains" in extract_spec["input"])

    for accumulator in accumulators.values():
        job = accumulator.job
        output = safe_response_path(responses_dir, job["outputFile"])
        output.parent.mkdir(parents=True, exist_ok=True)
        result = {
            "dataset": job["input"]["dataset"],
            "mode": "aggregate",
            "query": job["input"],
            "rows": accumulator.rows(),
            "nextCursor": None,
        }
        output.write_text(dump_json_exact(result, indent=2) + "\n", encoding="utf-8")


def cleanup_downloads(manifest: dict[str, Any], responses_dir: Path) -> None:
    if "sharedDownload" in manifest:
        from partition_download_plan import release_saved_report
        shared = require_object(manifest["sharedDownload"], "shared download reference")
        release_saved_report(Path(shared["indexPath"]), shared["reportId"])
        return
    extracts = manifest.get("extracts", [])
    if not isinstance(extracts, list):
        return
    for extract in extracts:
        if not isinstance(extract, dict) or not isinstance(extract.get("outputFile"), str):
            continue
        response_path = safe_response_path(responses_dir, extract["outputFile"])
        if not response_path.exists():
            continue
        try:
            response = unwrap_success_envelope(load_json(response_path, "saved partition download response"))
            directory = validate_extract_directory(response.get("localDirectory") if isinstance(response, dict) else None)
            shutil.rmtree(directory)
        except (ExtractError, OSError, ValueError):
            continue


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--registry-response", type=Path)
    parser.add_argument("--responses-dir", required=True, type=Path)
    parser.add_argument("--cleanup-only", action="store_true", help="Delete only launcher-owned extract directories named by saved responses.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    try:
        args = parse_args(argv)
        manifest = require_object(load_json(args.manifest, "query manifest"), "query manifest")
        if args.cleanup_only:
            cleanup_downloads(manifest, args.responses_dir)
            return 0
        if args.registry_response is None:
            raise ExtractError("--registry-response is required unless --cleanup-only is used")
        registry = require_object(load_json(args.registry_response, "registry response"), "registry response")
        materialize(manifest, registry, args.responses_dir)
    except (ExtractError, ValueError, OSError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
