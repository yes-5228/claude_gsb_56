"""监测数据录入业务逻辑 (含超标自动判定、覆盖版本留痕与并发冲突控制)."""
from datetime import datetime, time

from ..domain import exceedance_rules
from ..domain.standards import get_pollutant
from ..errors import ConflictError, NotFoundError, ValidationError, VersionConflictError
from ..extensions import db
from ..models import Exceedance, Measurement, MeasurementRevision, Station
from ..models.base import iso
from ..utils.validation import parse_date


def get_measurement(measurement_id):
    measurement = db.session.get(Measurement, measurement_id)
    if measurement is None:
        raise NotFoundError("监测数据不存在: id=%s" % measurement_id)
    return measurement


def preview_entries(period, entries):
    """Dry-run evaluation for the entry form (no database writes)."""
    results = []
    for entry in entries:
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


def _duplicate_payload(record, meta, new_value, evaluation):
    """重复数据的新旧对照, 供页面渲染差异对比后由录入人选择跳过或覆盖."""
    exceedance = record.exceedance
    return {
        "pollutant": record.pollutant,
        "pollutant_label": meta["label"],
        "unit": meta["unit"],
        "value": new_value,
        "value_diff": round(new_value - float(record.value), 6),
        "existing_id": record.id,
        "existing_value": record.value,
        "existing_version": record.version,
        "existing_recorder": record.recorder,
        "existing_updated_at": iso(record.updated_at),
        "existing_is_exceeded": bool(record.is_exceeded),
        "existing_exceed_ratio": record.exceed_ratio,
        "existing_limit_value": record.limit_value,
        "existing_level": exceedance.level if exceedance else None,
        "existing_annotation_status": exceedance.status if exceedance else None,
        "new_is_exceeded": evaluation["exceeded"],
        "new_exceed_ratio": evaluation["ratio"],
        "new_limit_value": evaluation["limit"],
        "new_level": evaluation["level"],
        "message": "该时刻 %s 数据已存在" % meta["label"],
    }


def _build_revision(record, new_value, evaluation, operator, reason):
    """为一次“数值发生变化”的覆盖生成版本快照; 数值未变时返回 None (不记版本)."""
    if float(record.value) == float(new_value):
        return None
    exceedance = record.exceedance
    return MeasurementRevision(
        measurement_id=record.id,
        version=record.version + 1,
        old_value=record.value,
        new_value=new_value,
        unit=record.unit,
        old_limit_value=record.limit_value,
        new_limit_value=evaluation["limit"],
        old_is_exceeded=bool(record.is_exceeded),
        new_is_exceeded=bool(evaluation["exceeded"]),
        old_exceed_ratio=record.exceed_ratio,
        new_exceed_ratio=evaluation["ratio"],
        old_level=exceedance.level if exceedance else None,
        new_level=evaluation["level"],
        prev_annotation_status=exceedance.status if exceedance else None,
        prev_annotator=exceedance.annotator if exceedance else None,
        prev_note=exceedance.note if exceedance else None,
        prev_annotated_at=exceedance.annotated_at if exceedance else None,
        operator=operator,
        reason=reason,
    )


def record_entries(station_id, measured_at, period, entries, data_source="manual",
                   recorder=None, remark=None, overwrite=False, overwrite_reason=None):
    """Persist one measured_at snapshot for a station.

    Duplicate (station, pollutant, period, measured_at) rows are reported back with
    an old/new diff payload; when ``overwrite`` is true the existing row is refreshed,
    a revision snapshot is stored and the exceedance conclusion is re-evaluated.
    Overwriting requires an operator (recorder) and a reason, and honours the
    per-entry ``expected_version`` optimistic lock: a stale version aborts the
    whole batch with a VERSION_CONFLICT error so only one side wins.
    """
    station = _load_station(station_id)
    if not entries:
        raise ValidationError("至少需要录入一条监测数据", fields={"entries": "empty"})

    operator = (recorder or "").strip()
    reason = (overwrite_reason or "").strip()
    if overwrite:
        fields = {}
        if not operator:
            fields["recorder"] = "覆盖已有数据时必须填写操作人"
        if not reason:
            fields["overwrite_reason"] = "覆盖已有数据时必须填写覆盖原因"
        if fields:
            raise ValidationError("覆盖已有数据时必须记录操作人与覆盖原因", fields=fields)

    existing = {
        row.pollutant: row
        for row in Measurement.query.filter_by(
            station_id=station.id, period=period, measured_at=measured_at
        ).all()
    }

    # 预检: 因子/数值校验 + 乐观锁版本核对, 任何一项失败都不写库
    prepared = []
    seen = set()
    version_conflicts = []
    for entry in entries:
        pollutant = str(entry.get("pollutant", "")).upper()
        meta = get_pollutant(pollutant)
        if meta is None:
            raise ValidationError(
                "未知监测因子: %s" % entry.get("pollutant"), fields={"pollutant": "unknown"}
            )
        if pollutant in seen:
            raise ValidationError(
                "%s 在同一时刻重复提交" % meta["label"], fields={pollutant: "duplicated_in_batch"}
            )
        seen.add(pollutant)

        try:
            value = float(entry.get("value"))
        except (TypeError, ValueError):
            raise ValidationError(
                "%s 监测值必须为数字" % meta["label"], fields={pollutant: "invalid_number"}
            )

        evaluation = exceedance_rules.evaluate(pollutant, period, value)
        record = existing.get(pollutant)

        if overwrite and record is not None:
            expected = entry.get("expected_version")
            if expected is not None and int(expected) != record.version:
                version_conflicts.append(
                    {
                        "pollutant": pollutant,
                        "pollutant_label": meta["label"],
                        "measurement_id": record.id,
                        "expected_version": int(expected),
                        "current_version": record.version,
                        "current_value": record.value,
                        "current_recorder": record.recorder,
                        "current_updated_at": iso(record.updated_at),
                    }
                )
        prepared.append((entry, pollutant, meta, value, evaluation, record))

    if version_conflicts:
        db.session.rollback()
        raise VersionConflictError(
            "以下因子刚被他人覆盖, 本次提交已取消, 请核对最新差异后重试: %s"
            % ", ".join(item["pollutant_label"] for item in version_conflicts),
            conflicts=version_conflicts,
        )

    created, updated, exceeded, duplicates, evaluated, revisions = [], [], [], [], [], []
    for entry, pollutant, meta, value, evaluation, record in prepared:
        evaluated.append(
            {
                "pollutant": pollutant,
                "pollutant_label": meta["label"],
                "value": value,
                "unit": meta["unit"],
                **evaluation,
            }
        )

        if record is not None and not overwrite:
            duplicates.append(_duplicate_payload(record, meta, value, evaluation))
            continue

        is_new = record is None
        revision = None
        if is_new:
            record = Measurement(station_id=station.id, pollutant=pollutant, period=period,
                                 measured_at=measured_at)
            db.session.add(record)
        else:
            revision = _build_revision(record, value, evaluation, operator, reason)

        record.value = value
        record.unit = meta["unit"]
        record.limit_value = evaluation["limit"]
        record.exceed_ratio = evaluation["ratio"]
        record.is_exceeded = evaluation["exceeded"]
        record.data_source = data_source
        record.recorder = entry.get("recorder") or recorder
        record.remark = entry.get("remark") or remark

        if revision is not None:
            record.version += 1
            revision.version = record.version
            db.session.add(revision)

        _sync_exceedance(record, meta, evaluation, revision=revision)
        db.session.flush()
        if revision is not None:
            revisions.append(revision.to_dict())
        (created if is_new else updated).append(record.to_dict(include_station=True))
        if evaluation["exceeded"]:
            exceeded.append(record.exceedance.to_dict() if record.exceedance else None)

    if not created and not updated and duplicates:
        raise ConflictError(
            "所选时刻已存在相同数据, 请核对新旧差异后选择跳过或覆盖已有数据: %s"
            % ", ".join(item["pollutant_label"] for item in duplicates),
            extra={"duplicates": duplicates, "evaluations": evaluated},
        )

    db.session.commit()
    return {
        "station": station.to_option(),
        "measured_at": measured_at.isoformat(timespec="seconds"),
        "period": period,
        "created": created,
        "updated": updated,
        "exceedances": [item for item in exceeded if item],
        "duplicates": duplicates,
        "evaluations": evaluated,
        "revisions": revisions,
        "summary": {
            "created_count": len(created),
            "updated_count": len(updated),
            "exceeded_count": len([item for item in evaluated if item["exceeded"]]),
            "duplicate_count": len(duplicates),
            "revision_count": len(revisions),
        },
    }


def _sync_exceedance(record, meta, evaluation, revision=None):
    """Create / refresh / drop the exceedance row attached to a measurement.

    覆盖导致数值变化时 (revision 非空), 超标结论按新数值重新判定:
    仍超标则更新记录并把原人工标注重置回待标注, 通过 reset_by_revision 溯源;
    不再超标则撤销记录, 原标注快照保留在 revision 中。
    """
    if evaluation["exceeded"]:
        if record.exceedance is None:
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
            )
        else:
            record.exceedance.value = record.value
            record.exceedance.limit_value = evaluation["limit"]
            record.exceedance.exceed_ratio = evaluation["ratio"]
            record.exceedance.level = evaluation["level"]
            record.exceedance.measured_at = record.measured_at
            if revision is not None and record.exceedance.status != "pending":
                record.exceedance.status = "pending"
                record.exceedance.note = None
                record.exceedance.annotator = None
                record.exceedance.annotated_at = None
                record.exceedance.reset_by_revision = revision
    elif record.exceedance is not None:
        db.session.delete(record.exceedance)


def delete_measurement(measurement):
    payload = measurement.to_dict()
    db.session.delete(measurement)
    db.session.commit()
    return payload


def measurement_revisions(measurement):
    """单条监测数据的覆盖版本, 按版本号倒序 (新的在前)."""
    rows = (
        MeasurementRevision.query.filter_by(measurement_id=measurement.id)
        .order_by(MeasurementRevision.version.desc())
        .all()
    )
    return {
        "measurement": measurement.to_dict(include_station=True),
        "items": [row.to_dict() for row in rows],
        "total": len(rows),
    }


def _revision_date(args, name, end_of_day=False):
    raw = args.get(name)
    if raw in (None, ""):
        return None
    parsed = parse_date(raw, name)
    return datetime.combine(parsed, time.max if end_of_day else time.min)


def revision_query(args):
    """覆盖版本的全局检索: 按时间倒序回看, 支持监测点/因子/操作人/时间范围."""
    query = MeasurementRevision.query.join(
        Measurement, MeasurementRevision.measurement_id == Measurement.id
    )

    station_id = args.get("station_id")
    if station_id not in (None, ""):
        try:
            query = query.filter(Measurement.station_id == int(station_id))
        except (TypeError, ValueError):
            raise ValidationError("station_id 参数必须为整数", fields={"station_id": "invalid_integer"})
    pollutant = (args.get("pollutant") or "").strip()
    if pollutant:
        query = query.filter(Measurement.pollutant == pollutant.upper())
    operator = (args.get("operator") or "").strip()
    if operator:
        query = query.filter(MeasurementRevision.operator.like("%" + operator + "%"))
    date_from = _revision_date(args, "date_from")
    if date_from:
        query = query.filter(MeasurementRevision.created_at >= date_from)
    date_to = _revision_date(args, "date_to", end_of_day=True)
    if date_to:
        query = query.filter(MeasurementRevision.created_at <= date_to)

    return query.order_by(MeasurementRevision.created_at.desc(), MeasurementRevision.id.desc())
