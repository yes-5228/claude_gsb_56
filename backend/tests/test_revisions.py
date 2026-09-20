"""覆盖差异对比、版本留痕、并发冲突与超标重算溯源的测试."""
from app.extensions import db
from app.models import Exceedance, Measurement, MeasurementRevision


def _overwrite_payload(entry_payload, station_id, entries, **overrides):
    base = {
        "overwrite": True,
        "overwrite_reason": "设备校准后复测修正",
    }
    base.update(overrides)
    return entry_payload(station_id, entries=entries, **base)


def test_duplicate_conflict_returns_diff_payload(client, station, entry_payload):
    client.post("/api/measurements/entries", json=entry_payload(station.id))
    response = client.post(
        "/api/measurements/entries",
        json=entry_payload(station.id, entries=[{"pollutant": "SO2", "value": 320.0}]),
    )
    assert response.status_code == 409
    error = response.get_json()["error"]
    assert error["code"] == "CONFLICT"
    duplicates = error["duplicates"]
    assert len(duplicates) == 1
    diff = duplicates[0]
    assert diff["pollutant"] == "SO2"
    assert diff["existing_value"] == 900.0
    assert diff["value"] == 320.0
    assert diff["value_diff"] == -580.0
    assert diff["existing_version"] == 1
    assert diff["existing_recorder"] == "测试员"
    assert diff["existing_is_exceeded"] is True
    assert diff["new_is_exceeded"] is False
    assert Measurement.query.count() == 3


def test_partial_duplicate_returns_201_with_diff(client, station, entry_payload):
    client.post("/api/measurements/entries", json=entry_payload(station.id))
    response = client.post(
        "/api/measurements/entries",
        json=entry_payload(
            station.id,
            entries=[{"pollutant": "SO2", "value": 320.0}, {"pollutant": "NO2", "value": 50.0}],
        ),
    )
    assert response.status_code == 201
    body = response.get_json()
    assert body["summary"]["created_count"] == 1
    assert body["summary"]["duplicate_count"] == 1
    assert body["duplicates"][0]["pollutant"] == "SO2"


def test_overwrite_requires_operator_and_reason(client, station, entry_payload):
    client.post("/api/measurements/entries", json=entry_payload(station.id))

    missing_reason = client.post(
        "/api/measurements/entries",
        json=entry_payload(
            station.id, overwrite=True, entries=[{"pollutant": "SO2", "value": 320.0}]
        ),
    )
    assert missing_reason.status_code == 422
    assert "overwrite_reason" in missing_reason.get_json()["error"]["fields"]

    missing_operator = client.post(
        "/api/measurements/entries",
        json=entry_payload(
            station.id,
            overwrite=True,
            overwrite_reason="复测修正",
            recorder="",
            entries=[{"pollutant": "SO2", "value": 320.0}],
        ),
    )
    assert missing_operator.status_code == 422
    assert "recorder" in missing_operator.get_json()["error"]["fields"]

    assert Measurement.query.filter_by(pollutant="SO2").one().value == 900.0
    assert MeasurementRevision.query.count() == 0


def test_overwrite_creates_revision_with_operator_and_reason(client, station, entry_payload):
    client.post("/api/measurements/entries", json=entry_payload(station.id))
    response = client.post(
        "/api/measurements/entries",
        json=_overwrite_payload(
            entry_payload,
            station.id,
            [{"pollutant": "SO2", "value": 320.0}],
            recorder="王敏",
        ),
    )
    assert response.status_code == 201
    body = response.get_json()
    assert body["summary"]["revision_count"] == 1

    record = Measurement.query.filter_by(pollutant="SO2").one()
    assert record.value == 320.0
    assert record.version == 2

    revision = MeasurementRevision.query.filter_by(measurement_id=record.id).one()
    assert revision.version == 2
    assert revision.old_value == 900.0
    assert revision.new_value == 320.0
    assert revision.old_is_exceeded is True
    assert revision.new_is_exceeded is False
    assert revision.operator == "王敏"
    assert revision.reason == "设备校准后复测修正"
    assert body["revisions"][0]["id"] == revision.id


def test_overwrite_same_value_does_not_create_revision(client, station, entry_payload):
    client.post("/api/measurements/entries", json=entry_payload(station.id))
    response = client.post(
        "/api/measurements/entries",
        json=_overwrite_payload(entry_payload, station.id, [{"pollutant": "SO2", "value": 900.0}]),
    )
    assert response.status_code == 201
    assert response.get_json()["summary"]["revision_count"] == 0
    record = Measurement.query.filter_by(pollutant="SO2").one()
    assert record.version == 1
    assert MeasurementRevision.query.count() == 0
    # 数值未变, 已生成的超标记录保持原状态
    assert Exceedance.query.count() == 1


def test_overwrite_resets_confirmed_annotation_and_traces_revision(
    client, station, entry_payload
):
    created = client.post("/api/measurements/entries", json=entry_payload(station.id)).get_json()
    exceedance_id = created["exceedances"][0]["id"]
    confirm = client.patch(
        "/api/exceedances/%d" % exceedance_id,
        json={"status": "confirmed", "note": "已核实为真实超标", "annotator": "李工"},
    )
    assert confirm.status_code == 200

    response = client.post(
        "/api/measurements/entries",
        json=_overwrite_payload(
            entry_payload,
            station.id,
            [{"pollutant": "SO2", "value": 760.0}],
            recorder="王敏",
        ),
    )
    assert response.status_code == 201

    exceedance = db.session.get(Exceedance, exceedance_id)
    # 标注状态按新数值重算: 回到待标注, 不沿用旧的确认结论
    assert exceedance.status == "pending"
    assert exceedance.note is None
    assert exceedance.annotator is None
    assert exceedance.annotated_at is None
    assert exceedance.value == 760.0

    # 能看出是哪一次覆盖导致结论变了
    revision = MeasurementRevision.query.filter_by(
        measurement_id=exceedance.measurement_id
    ).one()
    assert exceedance.reset_by_revision_id == revision.id
    assert revision.prev_annotation_status == "confirmed"
    assert revision.prev_annotator == "李工"
    assert revision.prev_note == "已核实为真实超标"

    detail = client.get("/api/exceedances/%d" % exceedance_id).get_json()
    trace = detail["reset_by_revision"]
    assert trace["version"] == 2
    assert trace["operator"] == "王敏"
    assert trace["reason"] == "设备校准后复测修正"
    assert trace["prev_annotation_status"] == "confirmed"
    assert trace["prev_annotator"] == "李工"


def test_overwrite_to_non_exceeded_keeps_annotation_snapshot_in_revision(
    client, station, entry_payload
):
    created = client.post("/api/measurements/entries", json=entry_payload(station.id)).get_json()
    exceedance_id = created["exceedances"][0]["id"]
    client.patch(
        "/api/exceedances/%d" % exceedance_id,
        json={"status": "confirmed", "note": "现场核查属实", "annotator": "李工"},
    )

    client.post(
        "/api/measurements/entries",
        json=_overwrite_payload(entry_payload, station.id, [{"pollutant": "SO2", "value": 120.0}]),
    )
    assert Exceedance.query.count() == 0

    # 超标记录被撤销, 但被覆盖掉的确认标注仍可在版本中回看
    revision = MeasurementRevision.query.one()
    assert revision.old_is_exceeded is True
    assert revision.new_is_exceeded is False
    assert revision.prev_annotation_status == "confirmed"
    assert revision.prev_annotator == "李工"
    assert revision.prev_note == "现场核查属实"


def test_concurrent_overwrite_only_one_wins(client, station, entry_payload):
    client.post("/api/measurements/entries", json=entry_payload(station.id))
    record = Measurement.query.filter_by(pollutant="SO2").one()
    stale_version = record.version

    first = client.post(
        "/api/measurements/entries",
        json=_overwrite_payload(
            entry_payload,
            station.id,
            [{"pollutant": "SO2", "value": 700.0, "expected_version": stale_version}],
            recorder="甲",
        ),
    )
    assert first.status_code == 201

    # 第二人基于过期版本号提交, 必须被拒绝且不改库
    second = client.post(
        "/api/measurements/entries",
        json=_overwrite_payload(
            entry_payload,
            station.id,
            [{"pollutant": "SO2", "value": 200.0, "expected_version": stale_version}],
            recorder="乙",
        ),
    )
    assert second.status_code == 409
    error = second.get_json()["error"]
    assert error["code"] == "VERSION_CONFLICT"
    conflict = error["conflicts"][0]
    assert conflict["pollutant"] == "SO2"
    assert conflict["expected_version"] == stale_version
    assert conflict["current_version"] == stale_version + 1
    assert conflict["current_value"] == 700.0
    assert conflict["current_recorder"] == "甲"

    record = Measurement.query.filter_by(pollutant="SO2").one()
    assert record.value == 700.0
    assert record.version == stale_version + 1
    assert MeasurementRevision.query.count() == 1


def test_version_conflict_aborts_whole_batch(client, station, entry_payload):
    client.post("/api/measurements/entries", json=entry_payload(station.id))
    stale_version = Measurement.query.filter_by(pollutant="SO2").one().version

    client.post(
        "/api/measurements/entries",
        json=_overwrite_payload(
            entry_payload,
            station.id,
            [{"pollutant": "SO2", "value": 700.0, "expected_version": stale_version}],
        ),
    )
    # 批量中一个因子版本过期 -> 整个批次不落库
    response = client.post(
        "/api/measurements/entries",
        json=_overwrite_payload(
            entry_payload,
            station.id,
            [
                {"pollutant": "SO2", "value": 200.0, "expected_version": stale_version},
                {"pollutant": "PM25", "value": 33.0, "expected_version": 1},
            ],
        ),
    )
    assert response.status_code == 409
    assert Measurement.query.filter_by(pollutant="PM25").one().value == 60.0
    assert MeasurementRevision.query.count() == 1


def test_measurement_revision_history_endpoint(client, station, entry_payload):
    client.post("/api/measurements/entries", json=entry_payload(station.id))
    record = Measurement.query.filter_by(pollutant="SO2").one()
    for value in (700.0, 620.0):
        client.post(
            "/api/measurements/entries",
            json=_overwrite_payload(
                entry_payload, station.id, [{"pollutant": "SO2", "value": value}]
            ),
        )

    body = client.get("/api/measurements/%d/revisions" % record.id).get_json()
    assert body["total"] == 2
    assert body["measurement"]["version"] == 3
    versions = [item["version"] for item in body["items"]]
    assert versions == [3, 2]
    newest = body["items"][0]
    assert newest["old_value"] == 700.0
    assert newest["new_value"] == 620.0
    assert newest["operator"] == "测试员"
    assert newest["reason"] == "设备校准后复测修正"

    missing = client.get("/api/measurements/9999/revisions")
    assert missing.status_code == 404


def test_global_revision_list_with_filters(client, station, second_station, entry_payload):
    client.post("/api/measurements/entries", json=entry_payload(station.id))
    client.post(
        "/api/measurements/entries",
        json=entry_payload(second_station.id, measured_at="2026-09-02 08:00"),
    )
    client.post(
        "/api/measurements/entries",
        json=_overwrite_payload(
            entry_payload, station.id, [{"pollutant": "SO2", "value": 700.0}], recorder="王敏"
        ),
    )
    client.post(
        "/api/measurements/entries",
        json=_overwrite_payload(
            entry_payload,
            second_station.id,
            [{"pollutant": "PM25", "value": 40.0}],
            measured_at="2026-09-02 08:00",
            recorder="李工",
        ),
    )

    body = client.get("/api/measurements/revisions").get_json()
    assert body["total"] == 2
    assert body["items"][0]["measurement"]["station_id"] in {station.id, second_station.id}

    by_station = client.get(
        "/api/measurements/revisions?station_id=%d" % station.id
    ).get_json()
    assert by_station["total"] == 1
    assert by_station["items"][0]["measurement"]["pollutant"] == "SO2"

    by_pollutant = client.get("/api/measurements/revisions?pollutant=pm25").get_json()
    assert by_pollutant["total"] == 1
    assert by_pollutant["items"][0]["operator"] == "李工"

    by_operator = client.get("/api/measurements/revisions?operator=王").get_json()
    assert by_operator["total"] == 1

    none_matched = client.get(
        "/api/measurements/revisions?date_from=2020-01-01&date_to=2020-01-02"
    ).get_json()
    assert none_matched["total"] == 0


def test_revision_versions_are_returned_in_measurement_list(client, station, entry_payload):
    client.post("/api/measurements/entries", json=entry_payload(station.id))
    client.post(
        "/api/measurements/entries",
        json=_overwrite_payload(entry_payload, station.id, [{"pollutant": "SO2", "value": 700.0}]),
    )
    body = client.get("/api/measurements?pollutant=SO2").get_json()
    assert body["items"][0]["version"] == 2
