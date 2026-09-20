"""监测数据录入业务逻辑 (含超标自动判定 / 覆盖审计 / 版本留痕)."""
from ..domain import exceedance_rules
from ..domain.constants import EXCEEDANCE_STATUS_LABELS, label_of
from ..domain.standards import get_pollutant
from ..errors import ConflictError, NotFoundError, ValidationError
from ..extensions import db
from ..models import (
    ACTION_CREATE,
    ACTION_OVERWRITE,
    CONCLUSION_UNCHANGED,
    Exceedance,
    Measurement,
    MeasurementVersion,
    Station,
    classify_conclusion_change,
)


def get_measurement(measurement_id):
    measurement = db.session.get(Measurement, measurement_id)
    if measurement is None:
        raise NotFoundError("监测数据不存在: id=%s" % measurement_id)
    return measurement


def preview_entries(period, entries):
    """Dry-run evaluation for the entry form (no database writes)."""
    results = []
    for entry in entries:
        pollutant, meta, value = _parse_entry(entry)
        evaluation = exceedance_rules.evaluate(pollutant, period, value)
        results.append(
            {
                "pollutant": pollutant,
                "pollutant_label": meta["label"],
                "value": value,
                "unit": meta["unit"],
                **evaluation,
            }
        )
    return {"period": period, "results": results, "summary": exceedance_rules.summarize(results)}


def _load_station(station_id):
    station = db.session.get(Station, station_id)
    if station is None:
        raise NotFoundError("监测点不存在: id=%s" % station_id)
    return station


def _parse_entry(entry):
    pollutant = str(entry.get("pollutant", "")).upper()
    meta = get_pollutant(pollutant)
    if meta is None:
        raise ValidationError("未知监测因子: %s" % entry.get("pollutant"), fields={"pollutant": "unknown"})
    try:
        value = float(entry.get("value"))
    except (TypeError, ValueError):
        raise ValidationError(
            "%s 监测值必须为数字" % meta["label"], fields={pollutant: "invalid_number"}
        )
    return pollutant, meta, value


def _entry_option(entry, top_level, key, default=None):
    """Per-entry override falling back to the top-level form value."""
    value = entry.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        value = top_level.get(key)
    return value if value is not None else default


def _existing_map(station, period, measured_at):
    rows = Measurement.query.filter_by(
        station_id=station.id, period=period, measured_at=measured_at
    ).all()
    return {row.pollutant: row for row in rows}


def _existing_payload(record, evaluation, incoming_value):
    """Diff information for one duplicate factor used by the pre-check dialog."""
    old_exceedance = record.exceedance
    before = {
        "exceeded": bool(record.is_exceeded),
        "level": old_exceedance.level if old_exceedance else None,
        "ratio": record.exceed_ratio,
    }
    change = classify_conclusion_change(before, evaluation)
    delta = round(incoming_value - record.value, 4)
    delta_percent = round((delta / record.value) * 100, 2) if record.value else None
    return {
        "pollutant": record.pollutant,
        "pollutant_label": record.pollutant_label(),
        "unit": record.unit,
        "existing_id": record.id,
        "version": record.version,
        "existing_value": record.value,
        "new_value": incoming_value,
        "delta": delta,
        "delta_percent": delta_percent,
        "existing": {
            "value": record.value,
            "is_exceeded": bool(record.is_exceeded),
            "level": before["level"],
            "ratio": record.exceed_ratio,
            "limit_value": record.limit_value,
            "status": old_exceedance.status if old_exceedance else None,
            "status_label": (
                label_of(EXCEEDANCE_STATUS_LABELS, old_exceedance.status)
                if old_exceedance
                else None
            ),
            "annotator": old_exceedance.annotator if old_exceedance else None,
            "annotated_at": old_exceedance.annotated_at.isoformat(timespec="seconds")
            if old_exceedance and old_exceedance.annotated_at
            else None,
            "note": old_exceedance.note if old_exceedance else None,
            "recorder": record.recorder,
        },
        "incoming": {
            "value": incoming_value,
            "is_exceeded": evaluation["exceeded"],
            "level": evaluation["level"],
            "ratio": evaluation["ratio"],
            "limit_value": evaluation["limit"],
            "applicable": evaluation["applicable"],
        },
        "conclusion_change": change,
        "annotation_will_reset": bool(
            old_exceedance
            and old_exceedance.status != "pending"
            and evaluation["exceeded"]
        ),
        "exceedance_will_revoke": bool(record.is_exceeded and not evaluation["exceeded"]),
    }


def check_duplicates(station_id, measured_at, period, entries):
    """Compare incoming entries against stored rows without writing anything.

    Returns per-factor old/new value diffs and the re-evaluated exceedance
    conclusion so the entry page can let the recorder skip or overwrite.
    """
    station = _load_station(station_id)
    if not entries:
        raise ValidationError("至少需要录入一条监测数据", fields={"entries": "empty"})

    existing = _existing_map(station, period, measured_at)
    duplicates, new_items = [], []
    seen = set()
    for entry in entries:
        pollutant, meta, value = _parse_entry(entry)
        if pollutant in seen:
            raise ValidationError(
                "%s 在同一时刻重复提交" % meta["label"], fields={pollutant: "duplicated_in_batch"}
            )
        seen.add(pollutant)
        evaluation = exceedance_rules.evaluate(pollutant, period, value)
        record = existing.get(pollutant)
        if record is None:
            new_items.append(
                {
                    "pollutant": pollutant,
                    "pollutant_label": meta["label"],
                    "value": value,
                    "unit": meta["unit"],
                    **evaluation,
                }
            )
        else:
            duplicates.append(_existing_payload(record, evaluation, value))

    return {
        "station": station.to_option(),
        "measured_at": measured_at.isoformat(timespec="seconds"),
        "period": period,
        "duplicates": duplicates,
        "new": new_items,
        "summary": {
            "duplicate_count": len(duplicates),
            "new_count": len(new_items),
            "annotated_count": len([item for item in duplicates if item["annotation_will_reset"]]),
        },
    }


def record_entries(station_id, measured_at, period, entries, data_source="manual",
                   recorder=None, remark=None, overwrite=False, operator=None, reason=None):
    """Persist one measured_at snapshot for a station.

    Existing rows are skipped by default. An entry (or the whole request) may
    opt into overwrite, which requires an operator + reason and a base_version
    for optimistic concurrency control. Overwrites never reuse the previous
    exceedance conclusion/annotation: the exceedance record is rebuilt from the
    new value and every change is kept as an immutable MeasurementVersion.
    """
    station = _load_station(station_id)
    if not entries:
        raise ValidationError("至少需要录入一条监测数据", fields={"entries": "empty"})

    top_level = {"overwrite": overwrite, "operator": operator, "reason": reason}
    existing = _existing_map(station, period, measured_at)

    created, updated, duplicates, evaluated, changes = [], [], [], [], []
    version_conflicts = []
    seen = set()

    for entry in entries:
        pollutant, meta, value = _parse_entry(entry)
        if pollutant in seen:
            raise ValidationError(
                "%s 在同一时刻重复提交" % meta["label"], fields={pollutant: "duplicated_in_batch"}
            )
        seen.add(pollutant)

        evaluation = exceedance_rules.evaluate(pollutant, period, value)
        evaluated.append(
            {
                "pollutant": pollutant,
                "pollutant_label": meta["label"],
                "value": value,
                "unit": meta["unit"],
                **evaluation,
            }
        )

        record = existing.get(pollutant)
        # 条目显式声明 overwrite 时以条目为准; 缺省时回退顶层开关
        entry_overwrite = entry.get("overwrite")
        if entry_overwrite is None:
            wants_overwrite = bool(top_level.get("overwrite"))
        else:
            wants_overwrite = bool(entry_overwrite)

        if record is not None and not wants_overwrite:
            duplicates.append(
                {
                    "pollutant": pollutant,
                    "pollutant_label": meta["label"],
                    "value": value,
                    "existing_id": record.id,
                    "version": record.version,
                    "message": "该时刻 %s 数据已存在" % meta["label"],
                }
            )
            continue

        entry_operator = _entry_option(entry, top_level, "operator")
        entry_reason = _entry_option(entry, top_level, "reason")

        if record is not None:
            base_version = entry.get("base_version")
            if entry_operator is None or not str(entry_operator).strip():
                raise ValidationError(
                    "覆盖 %s 数据必须填写操作人" % meta["label"],
                    fields={"operator": "required_for_overwrite"},
                )
            if entry_reason is None or not str(entry_reason).strip():
                raise ValidationError(
                    "覆盖 %s 数据必须填写覆盖原因" % meta["label"],
                    fields={"reason": "required_for_overwrite"},
                )
            if base_version is None:
                raise ValidationError(
                    "覆盖 %s 数据缺少版本号, 请重新比对后再提交" % meta["label"],
                    fields={"base_version": "required"},
                )
            try:
                base_version = int(base_version)
            except (TypeError, ValueError):
                raise ValidationError(
                    "%s 版本号不合法" % meta["label"], fields={"base_version": "invalid"}
                )
            if base_version != record.version:
                version_conflicts.append(
                    {
                        "pollutant": pollutant,
                        "pollutant_label": meta["label"],
                        "existing_id": record.id,
                        "expected_version": base_version,
                        "current_version": record.version,
                        "current_value": record.value,
                        "message": "%s 已被他人覆盖到第 %d 版" % (meta["label"], record.version),
                    }
                )
                continue

            try:
                change = _apply_overwrite(
                    record=record,
                    meta=meta,
                    evaluation=evaluation,
                    value=value,
                    data_source=data_source,
                    recorder=entry.get("recorder") or recorder,
                    remark=entry.get("remark") or remark,
                    operator=str(entry_operator).strip(),
                    reason=str(entry_reason).strip(),
                    base_version=base_version,
                )
            except _StaleVersion as stale:
                db.session.rollback()
                raise ConflictError(
                    "数据已被其他操作人更新, 本次覆盖未生效, 请刷新差异后重新选择",
                    details={
                        "kind": "version_conflict",
                        "conflicts": [
                            {
                                "pollutant": pollutant,
                                "pollutant_label": stale.label,
                                "existing_id": stale.record.id,
                                "expected_version": base_version,
                                "current_version": base_version + 1,
                                "message": "%s 已被他人覆盖" % stale.label,
                            }
                        ],
                    },
                )
            updated.append(record.to_dict(include_station=True))
            changes.append(change)
            continue

        record = Measurement(station_id=station.id, pollutant=pollutant, period=period,
                             measured_at=measured_at, version=1)
        record.value = value
        record.unit = meta["unit"]
        record.limit_value = evaluation["limit"]
        record.exceed_ratio = evaluation["ratio"]
        record.is_exceeded = evaluation["exceeded"]
        record.data_source = data_source
        record.recorder = entry.get("recorder") or recorder
        record.remark = entry.get("remark") or remark
        db.session.add(record)
        db.session.flush()
        _create_initial_version(record, evaluation)
        created.append(record.to_dict(include_station=True))

    if version_conflicts:
        db.session.rollback()
        raise ConflictError(
            "数据已被其他操作人更新, 本次覆盖未生效, 请刷新差异后重新选择",
            details={"kind": "version_conflict", "conflicts": version_conflicts},
        )

    if not created and not updated and duplicates:
        raise ConflictError(
            "所选时刻已存在相同数据, 请比对新旧数值后选择跳过或覆盖: %s"
            % ", ".join(item["pollutant_label"] for item in duplicates),
            details={"kind": "duplicate", "duplicates": duplicates},
        )

    db.session.commit()
    return {
        "station": station.to_option(),
        "measured_at": measured_at.isoformat(timespec="seconds"),
        "period": period,
        "created": created,
        "updated": updated,
        "exceedances": _current_exceedances(created + updated),
        "duplicates": duplicates,
        "evaluations": evaluated,
        "conclusion_changes": changes,
        "summary": {
            "created_count": len(created),
            "updated_count": len(updated),
            "exceeded_count": len([item for item in evaluated if item["exceeded"]]),
            "duplicate_count": len(duplicates),
            "annotation_reset_count": len(
                [item for item in changes if item["annotation_reset"]]
            ),
            "conclusion_changed_count": len(
                [item for item in changes if item["conclusion_change"] != CONCLUSION_UNCHANGED]
            ),
        },
    }


def _current_exceedances(rows_payload):
    ids = [item["id"] for item in rows_payload]
    if not ids:
        return []
    rows = Exceedance.query.filter(Exceedance.measurement_id.in_(ids)).all()
    return [row.to_dict() for row in rows]


def _create_initial_version(record, evaluation):
    """Snapshot a freshly created measurement (version 1)."""
    version = MeasurementVersion(
        measurement_id=record.id,
        station_id=record.station_id,
        version=1,
        action=ACTION_CREATE,
        pollutant=record.pollutant,
        period=record.period,
        value=record.value,
        unit=record.unit,
        limit_value=evaluation["limit"],
        exceed_ratio=evaluation["ratio"],
        is_exceeded=evaluation["exceeded"],
        level=evaluation["level"],
        measured_at=record.measured_at,
        data_source=record.data_source,
        recorder=record.recorder,
        remark=record.remark,
    )
    db.session.add(version)
    db.session.flush()
    if evaluation["exceeded"]:
        record.exceedance = Exceedance(
            station_id=record.station_id,
            pollutant=record.pollutant,
            period=record.period,
            measured_at=record.measured_at,
            value=record.value,
            limit_value=evaluation["limit"],
            exceed_ratio=evaluation["ratio"],
            level=evaluation["level"],
            status="pending",
            source_version_id=version.id,
            regenerated=False,
        )


def _apply_overwrite(record, meta, evaluation, value, data_source, recorder, remark,
                     operator, reason, base_version):
    """Conditionally overwrite one row; rebuild its exceedance from scratch."""
    old_exceedance = record.exceedance
    old_info = {
        "value": record.value,
        "is_exceeded": bool(record.is_exceeded),
        "level": old_exceedance.level if old_exceedance else None,
        "ratio": record.exceed_ratio,
        "status": old_exceedance.status if old_exceedance else None,
        "annotator": old_exceedance.annotator if old_exceedance else None,
        "annotated_at": old_exceedance.annotated_at if old_exceedance else None,
        "note": old_exceedance.note if old_exceedance else None,
        "exceedance_id": old_exceedance.id if old_exceedance else None,
    }
    change = classify_conclusion_change(
        {"exceeded": old_info["is_exceeded"], "level": old_info["level"]},
        evaluation,
    )

    # Atomic compare-and-set: WHERE version = base_version guarantees that two
    # concurrent overwrites against the same base version can only win once.
    new_version_number = base_version + 1
    affected = (
        db.session.query(Measurement)
        .filter(Measurement.id == record.id, Measurement.version == base_version)
        .update(
            {
                Measurement.value: value,
                Measurement.unit: meta["unit"],
                Measurement.limit_value: evaluation["limit"],
                Measurement.exceed_ratio: evaluation["ratio"],
                Measurement.is_exceeded: evaluation["exceeded"],
                Measurement.data_source: data_source,
                Measurement.recorder: recorder,
                Measurement.remark: remark,
                Measurement.version: Measurement.version + 1,
            },
            synchronize_session=False,
        )
    )
    if affected == 0:
        # Lost the race against a concurrent overwrite; caller rolls back.
        raise _StaleVersion(record, meta["label"], new_version_number)

    db.session.expire(record)
    record = db.session.get(Measurement, record.id)

    # Drop the old exceedance row (and its annotation) — conclusions and
    # annotation status must never carry over from the replaced value.
    if old_exceedance is not None:
        db.session.delete(old_exceedance)
        record.exceedance = None
        db.session.flush()

    snapshot = MeasurementVersion(
        measurement_id=record.id,
        station_id=record.station_id,
        version=new_version_number,
        action=ACTION_OVERWRITE,
        pollutant=record.pollutant,
        period=record.period,
        value=value,
        unit=meta["unit"],
        limit_value=evaluation["limit"],
        exceed_ratio=evaluation["ratio"],
        is_exceeded=evaluation["exceeded"],
        level=evaluation["level"],
        measured_at=record.measured_at,
        data_source=data_source,
        recorder=recorder,
        remark=remark,
        operator=operator,
        reason=reason,
        previous_value=old_info["value"],
        previous_is_exceeded=old_info["is_exceeded"],
        previous_level=old_info["level"],
        previous_exceed_ratio=old_info["ratio"],
        conclusion_change=change,
        previous_status=old_info["status"],
        previous_annotator=old_info["annotator"],
        previous_annotated_at=old_info["annotated_at"],
        previous_note=old_info["note"],
        previous_exceedance_id=old_info["exceedance_id"],
    )
    db.session.add(snapshot)
    db.session.flush()

    if evaluation["exceeded"]:
        record.exceedance = Exceedance(
            station_id=record.station_id,
            pollutant=record.pollutant,
            period=record.period,
            measured_at=record.measured_at,
            value=value,
            limit_value=evaluation["limit"],
            exceed_ratio=evaluation["ratio"],
            level=evaluation["level"],
            status="pending",
            source_version_id=snapshot.id,
            regenerated=True,
        )
    db.session.flush()

    return {
        "measurement_id": record.id,
        "pollutant": record.pollutant,
        "pollutant_label": meta["label"],
        "version": new_version_number,
        "operator": operator,
        "reason": reason,
        "old_value": old_info["value"],
        "new_value": value,
        "conclusion_change": change,
        "old_status": old_info["status"],
        "annotation_reset": bool(
            old_info["status"] in ("confirmed", "ignored") and evaluation["exceeded"]
        ),
        "exceedance_revoked": bool(old_info["is_exceeded"] and not evaluation["exceeded"]),
        "operated_at": snapshot.operated_at.isoformat(timespec="seconds"),
    }


class _StaleVersion(Exception):
    """Internal: compare-and-set lost the race during flush."""

    def __init__(self, record, label, attempted_version):
        self.record = record
        self.label = label
        self.attempted_version = attempted_version


def list_versions(measurement_id):
    measurement = get_measurement(measurement_id)
    versions = (
        MeasurementVersion.query.filter_by(measurement_id=measurement_id)
        .order_by(MeasurementVersion.version.desc(), MeasurementVersion.id.desc())
        .all()
    )
    return {
        "measurement": {
            "id": measurement.id,
            "station_id": measurement.station_id,
            "pollutant": measurement.pollutant,
            "pollutant_label": measurement.pollutant_label(),
            "period": measurement.period,
            "measured_at": measurement.measured_at.isoformat(timespec="seconds"),
            "current_version": measurement.version,
            "current_value": measurement.value,
            "unit": measurement.unit,
        },
        "items": [version.to_dict() for version in versions],
    }


def list_conclusion_changes(args):
    """Overwrite versions that changed an exceedance conclusion.

    This is how an already confirmed/ignored annotation stays traceable after
    recomputation: each event points at the exact overwrite that replaced it.
    """
    query = (
        MeasurementVersion.query.filter(MeasurementVersion.action == ACTION_OVERWRITE)
        .filter(MeasurementVersion.conclusion_change.isnot(None))
        .filter(MeasurementVersion.conclusion_change != CONCLUSION_UNCHANGED)
        .join(Station, MeasurementVersion.station_id == Station.id)
    )

    pollutant = (args.get("pollutant") or "").strip().upper()
    if pollutant:
        query = query.filter(MeasurementVersion.pollutant == pollutant)
    station_id = args.get("station_id")
    if station_id:
        try:
            query = query.filter(MeasurementVersion.station_id == int(station_id))
        except ValueError:
            raise ValidationError("station_id 必须为整数", fields={"station_id": "invalid"})
    if str(args.get("confirmed_only", "")).strip().lower() in {"1", "true", "yes"}:
        query = query.filter(MeasurementVersion.previous_status.in_(("confirmed", "ignored")))

    query = query.order_by(
        MeasurementVersion.operated_at.desc(), MeasurementVersion.id.desc()
    )
    rows = query.limit(200).all()

    def _event(version):
        payload = version.to_dict()
        payload["affected_annotation"] = version.previous_status in ("confirmed", "ignored")
        payload["station_name"] = version.measurement.station.name if (
            version.measurement and version.measurement.station
        ) else None
        payload["station_code"] = version.measurement.station.code if (
            version.measurement and version.measurement.station
        ) else None
        return payload

    items = [_event(row) for row in rows]
    return {
        "items": items,
        "total": len(items),
        "summary": {
            "total": len(items),
            "affected_annotation_count": len([item for item in items if item["affected_annotation"]]),
        },
    }


def delete_measurement(measurement):
    payload = measurement.to_dict()
    db.session.delete(measurement)
    db.session.commit()
    return payload
