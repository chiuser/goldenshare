"""Date candidates, SQL-only missing-key union and guarded atomic publication."""

from functools import partial
from pathlib import Path
from uuid import uuid4

from orchestrator.defs.bootstrap.moneyflow_history_candidates import (
    _identity,
    _receipt_scope,
    _validate_receipt,
    build_moneyflow_history_unit_candidates,
)
from orchestrator.defs.bootstrap.moneyflow_history_plan import (
    MoneyflowHistoryDateCount,
    build_moneyflow_history_plan,
    history_schema,
)
from orchestrator.defs.bootstrap.moneyflow_history_receive import (
    audit_history_day,
    history_candidate_connection,
)
from orchestrator.defs.bootstrap.moneyflow_history_supplement_control import (
    CUTOFF,
    child_directory,
    digest,
    file_hash,
    read_json,
    require,
    save_json,
    target,
)
from orchestrator.defs.checks.moneyflow import audit_market_moneyflow_file
from orchestrator.defs.checks.moneyflow_daily import audit_daily_moneyflow_file
from orchestrator.defs.io.moneyflow_update_publication import (
    publish_moneyflow_update_file,
)


def date_plan(entry):
    count = len(entry["keys"])
    return build_moneyflow_history_plan(
        entry["dataset"],
        [MoneyflowHistoryDateCount(entry["day"], count, count)],
        cutoff=CUTOFF,
    )


def keys(db, path, dataset):
    field = "trade_date" if dataset == "moneyflow_mkt_dc" else "ts_code"
    values = db.execute(
        f'SELECT "{field}" FROM read_parquet(?,hive_partitioning=false) '
        f'ORDER BY "{field}" LIMIT 10001',
        [str(path)],
    ).fetchall()
    require(len(values) <= 10000, "key_budget")
    return [
        v[0][:4] + "-" + v[0][4:6] + "-" + v[0][6:]
        if dataset == "moneyflow_mkt_dc"
        else v[0]
        for v in values
    ]


def audit_pair(db, entry, paths):
    count = audit_history_day(
        db, paths["raw"], paths["silver"], entry["day"], dataset=entry["dataset"]
    )
    require(
        count == len(entry["keys"])
        and keys(db, paths["raw"], entry["dataset"]) == entry["keys"],
        "source_key_mismatch",
    )


def candidates(entry, plan, source, control):
    dataset, day = entry["dataset"], entry["day"]
    directory = child_directory(
        Path(plan["staging_root"]), plan["operation_id"], dataset, day
    )
    receipt_path = directory / "unit-000000/checkpoint.json"
    p = date_plan(entry)
    if not receipt_path.exists() or read_json(receipt_path).get("stage") != "verified":
        build_moneyflow_history_unit_candidates(
            p,
            0,
            staging_root=Path(plan["staging_root"]),
            operation_id=plan["operation_id"] + "-" + day.replace("-", ""),
            source=source,
            cancel=lambda: control.check() or False,
            clock=control.clock,
        )
    receipt = read_json(receipt_path)
    _validate_receipt(receipt, _receipt_scope(p, 0, _identity(p)))
    require(
        receipt["stage"] == "verified" and receipt["difference_count"] == 0,
        "source_receipt",
    )
    require(
        receipt["source_proof"]["rows"] == len(entry["keys"])
        and receipt["verification_proof"]["rows"] == len(entry["keys"]),
        "source_proof",
    )
    fact = receipt["files"][0]
    base = directory / "unit-000000" / receipt["attempt"] / day
    paths = {layer: base / (layer + ".parquet") for layer in ("raw", "silver")}
    original_paths = dict(paths)
    for layer, path in paths.items():
        if not path.exists():
            paths[layer] = target(Path(plan["lake_root"]), dataset, day, layer)
        require(
            file_hash(paths[layer]) == fact[layer + "_sha256"],
            "source_candidate_changed",
        )
    with history_candidate_connection(directory, control.check) as db:
        audit_pair(db, entry, paths)
    return {
        "receipt": str(receipt_path),
        "receipt_sha256": file_hash(receipt_path),
        "paths": {k: str(v) for k, v in original_paths.items()},
        "hashes": {layer: fact[layer + "_sha256"] for layer in paths},
    }


def _difference(db, left, right):
    return db.execute(
        f"SELECT count(*) FROM (({left} EXCEPT {right}) UNION ALL "
        f"({right} EXCEPT {left}))"
    ).fetchone()[0]


def merge_dc(db, entry, source_raw, old_raw, old_silver, directory, control):
    """All business rows stay columnar; Python sees only counts and identity keys."""
    audit_history_day(db, old_raw, old_silver, entry["day"], dataset="moneyflow_dc")
    db.execute(
        "CREATE TEMP TABLE old_rows AS SELECT * FROM read_parquet(?,hive_partitioning=false)",
        [str(old_raw)],
    )
    db.execute(
        "CREATE TEMP TABLE prod_rows AS SELECT * FROM read_parquet(?,hive_partitioning=false)",
        [str(source_raw)],
    )
    require(
        db.execute(
            "SELECT count(*) FROM old_rows ANTI JOIN prod_rows "
            "USING(trade_date,ts_code)"
        ).fetchone()[0]
        == 0,
        "old_key_missing_from_prod",
    )
    db.execute(
        "CREATE TEMP TABLE added_rows AS SELECT prod_rows.* FROM prod_rows ANTI JOIN old_rows "
        "USING(trade_date,ts_code)"
    )
    db.execute(
        "CREATE TEMP TABLE final_rows AS SELECT * FROM old_rows UNION ALL SELECT * FROM added_rows"
    )
    old_diff = _difference(
        db,
        "SELECT * FROM old_rows",
        "SELECT final_rows.* FROM final_rows "
        "SEMI JOIN old_rows USING(trade_date,ts_code)",
    )
    added_diff = _difference(
        db,
        "SELECT * FROM added_rows",
        "SELECT final_rows.* FROM final_rows "
        "ANTI JOIN old_rows USING(trade_date,ts_code)",
    )
    require(old_diff == added_diff == 0, "merge_changed_values")
    counts = [
        db.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        for name in ("old_rows", "added_rows", "final_rows")
    ]
    require(counts[1] > 0 and counts[2] == len(entry["keys"]), "merge_counts")
    directory.mkdir(exist_ok=True)
    paths = {layer: directory / (layer + ".parquet") for layer in ("raw", "silver")}
    fields = ",".join(
        "strptime(trade_date,'%Y%m%d')::DATE AS trade_date"
        if c.name == "trade_date"
        else f'"{c.name}"'
        for c in history_schema("moneyflow_dc")
    )
    for layer, query in (
        ("raw", "SELECT * FROM final_rows ORDER BY trade_date,ts_code"),
        ("silver", f"SELECT {fields} FROM final_rows ORDER BY trade_date,ts_code"),
    ):
        control.check()
        require(not paths[layer].exists(), "merge_candidate_exists")
        db.execute(
            f"COPY ({query}) TO $path (FORMAT PARQUET)", {"path": str(paths[layer])}
        )
    audit_pair(db, entry, paths)
    return {
        "paths": {k: str(v) for k, v in paths.items()},
        "hashes": {k: file_hash(v) for k, v in paths.items()},
        "old_hashes": {"raw": file_hash(old_raw), "silver": file_hash(old_silver)},
        "prod_raw_sha256": file_hash(source_raw),
        "counts": counts,
        "old_value_differences": old_diff,
        "new_value_differences": added_diff,
        "added_keys_sha256": digest(
            db.execute("SELECT ts_code FROM added_rows ORDER BY ts_code").fetchall()
        ),
    }


def final_candidates(entry, source, plan, item, directory, control):
    proof_path = directory / "final-proof.json"
    if proof_path.exists():
        proof = read_json(proof_path)
        if item.get("proof_sha256"):
            require(
                file_hash(proof_path) == item["proof_sha256"], "merge_proof_changed"
            )
    else:
        if entry["dataset"] == "moneyflow_dc":
            lake = Path(plan["lake_root"])
            old = {
                layer: target(lake, entry["dataset"], entry["day"], layer)
                for layer in ("raw", "silver")
            }
            require(
                all(file_hash(old[k]) == entry["baseline"][k]["hash"] for k in old),
                "old_target_changed",
            )
            with history_candidate_connection(directory, control.check) as db:
                proof = merge_dc(
                    db,
                    entry,
                    Path(source["paths"]["raw"]),
                    old["raw"],
                    old["silver"],
                    directory / ("merged-" + uuid4().hex),
                    control,
                )
        else:
            proof = {"paths": source["paths"], "hashes": source["hashes"]}
        proof.update(
            source_receipt_sha256=source["receipt_sha256"], plan_sha256=control.sha
        )
        save_json(proof_path, proof)
    require(
        proof["plan_sha256"] == control.sha
        and proof["source_receipt_sha256"] == source["receipt_sha256"],
        "proof_identity",
    )
    if entry["dataset"] == "moneyflow_dc":
        require(
            proof["old_hashes"] == {k: v["hash"] for k, v in entry["baseline"].items()}
            and proof["prod_raw_sha256"] == source["hashes"]["raw"]
            and proof["counts"]
            == [
                entry["old_rows"],
                len(entry["keys"]) - entry["old_rows"],
                len(entry["keys"]),
            ]
            and proof["old_value_differences"] == proof["new_value_differences"] == 0,
            "merge_proof_identity",
        )
    else:
        require(
            proof["hashes"] == source["hashes"] and proof["paths"] == source["paths"],
            "passthrough_proof",
        )
    item["proof_sha256"] = file_hash(proof_path)
    item["hashes"] = proof["hashes"]
    control.save()
    return proof


def publish(entry, plan, proof, directory, control):
    lake = Path(plan["lake_root"])
    paths = {
        layer: target(lake, entry["dataset"], entry["day"], layer)
        for layer in ("raw", "silver")
    }
    auditor = (
        audit_market_moneyflow_file
        if entry["dataset"] == "moneyflow_mkt_dc"
        else partial(audit_daily_moneyflow_file, dataset=entry["dataset"])
    )
    with history_candidate_connection(directory, control.check) as db:
        effective = {}
        for layer, path in paths.items():
            new_hash = proof["hashes"][layer]
            old_hash = entry["baseline"][layer]["hash"]
            checkpoint = directory / (layer + "-publication.json")
            require(file_hash(path) in {old_hash, new_hash}, "target_changed")
            if checkpoint.exists():
                state = read_json(checkpoint)
                require(
                    state["candidate_sha256"] == new_hash
                    and state["prior_sha256"] == old_hash
                    and state["published_sha256"] == new_hash,
                    "publication_identity",
                )
            candidate = Path(proof["paths"][layer])
            require(
                file_hash(candidate) == new_hash
                or (
                    checkpoint.exists()
                    and file_hash(path) == new_hash
                    and not candidate.exists()
                ),
                "final_candidate_changed",
            )
            effective[layer] = path if file_hash(path) == new_hash else candidate
        audit_pair(db, entry, effective)
        for layer, path in paths.items():
            control.state["stage"] = "publishing_" + layer
            control.check()
            publish_moneyflow_update_file(
                db,
                Path(proof["paths"][layer]),
                path,
                dataset=entry["dataset"],
                audit_file=auditor,
                day=entry["day"],
                layer=layer,
                checkpoint=directory / (layer + "-publication.json"),
                raw_hash=proof["hashes"]["raw"] if layer == "silver" else None,
                check_cancel=control.check,
            )
        audit_pair(db, entry, paths)
    return paths
