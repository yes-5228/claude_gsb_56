"""监测数据录入接口测试."""
from app.models import Exceedance, Measurement


def test_batch_entry_creates_records_and_flags_exceedance(client, station, entry_payload):
    response = client.post("/api/measurements/entries", json=entry_payload(station.id))
    assert response.status_code == 201
    body = response.get_json()
    assert body["summary"]["created_count"] == 3
    assert body["summary"]["exceeded_count"] == 1
    assert len(body["exceedances"]) == 1
    assert body["exceedances"][0]["pollutant"] == "SO2"
    assert body["exceedances"][0]["status"] == "pending"
    assert body["station"]["code"] == "TEST-001"

    stored = Measurement.query.filter_by(pollutant="SO2").one()
    assert stored.is_exceeded is True
    assert stored.limit_value == 500.0
    assert stored.exceed_ratio == 1.8
    assert stored.unit == "μg/m³"
    assert stored.recorder == "测试员"


def test_duplicate_entry_is_reported_as_conflict(client, station, entry_payload):
    payload = entry_payload(station.id)
    client.post("/api/measurements/entries", json=payload)
    response = client.post("/api/measurements/entries", json=payload)
    assert response.status_code == 409
    body = response.get_json()
    assert "跳过或覆盖" in body["error"]["message"]
    assert body["error"]["details"]["kind"] == "duplicate"
    assert body["error"]["details"]["duplicates"][0]["pollutant"] == "PM25"
    assert Measurement.query.count() == 3


def test_conflicts_precheck_reports_old_new_diff(client, station, entry_payload):
    client.post("/api/measurements/entries", json=entry_payload(station.id))
    response = client.post(
        "/api/measurements/conflicts",
        json=entry_payload(station.id, entries=[{"pollutant": "SO2", "value": 480.0}]),
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["summary"]["duplicate_count"] == 1
    diff = body["duplicates"][0]
    assert diff["existing_value"] == 900.0
    assert diff["new_value"] == 480.0
    assert diff["delta"] == -420.0
    assert diff["version"] == 1
    # 旧值超标(重度), 新值达标
    assert diff["existing"]["is_exceeded"] is True
    assert diff["incoming"]["is_exceeded"] is False
    assert diff["conclusion_change"] == "exceeded_to_normal"


def test_overwrite_requires_operator_reason_and_base_version(client, station, entry_payload):
    client.post("/api/measurements/entries", json=entry_payload(station.id))

    missing_meta = client.post(
        "/api/measurements/entries",
        json=entry_payload(
            station.id,
            overwrite=True,
            entries=[{"pollutant": "SO2", "value": 120.0}],
        ),
    )
    assert missing_meta.status_code == 422
    assert missing_meta.get_json()["error"]["fields"]["operator"] == "required_for_overwrite"

    no_version = client.post(
        "/api/measurements/entries",
        json=entry_payload(
            station.id,
            overwrite=True,
            operator="王敏",
            reason="设备比对后修正",
            entries=[{"pollutant": "SO2", "value": 120.0}],
        ),
    )
    assert no_version.status_code == 422
    assert no_version.get_json()["error"]["fields"]["base_version"] == "required"


def test_overwrite_updates_record_and_clears_exceedance(client, station, entry_payload):
    client.post("/api/measurements/entries", json=entry_payload(station.id))
    assert Exceedance.query.count() == 1

    response = client.post(
        "/api/measurements/entries",
        json=entry_payload(
            station.id,
            overwrite=True,
            operator="王敏",
            reason="设备比对后修正",
            entries=[{"pollutant": "SO2", "value": 120.0, "base_version": 1}],
        ),
    )
    assert response.status_code == 201
    body = response.get_json()
    assert body["summary"]["created_count"] == 0
    assert body["summary"]["updated_count"] == 1
    assert body["summary"]["exceeded_count"] == 0
    record = Measurement.query.filter_by(pollutant="SO2").one()
    assert record.is_exceeded is False
    assert record.version == 2
    assert Exceedance.query.count() == 0
    change = body["conclusion_changes"][0]
    assert change["conclusion_change"] == "exceeded_to_normal"
    assert change["operator"] == "王敏"
    assert change["reason"] == "设备比对后修正"


def test_overwrite_rebuilds_exceedance_and_resets_confirmed_annotation(
    client, station, entry_payload
):
    from app.models import MeasurementVersion

    client.post(
        "/api/measurements/entries",
        json=entry_payload(station.id, entries=[{"pollutant": "SO2", "value": 900.0}]),
    )
    exceedance_id = Exceedance.query.filter_by(pollutant="SO2").one().id
    client.patch(
        "/api/exceedances/%d" % exceedance_id,
        json={"status": "confirmed", "note": "现场确认属实", "annotator": "李静"},
    )

    # 覆盖成另一个仍然超标的值: 结论重判, 旧的"已确认"不能沿用
    response = client.post(
        "/api/measurements/entries",
        json=entry_payload(
            station.id,
            overwrite=True,
            operator="王敏",
            reason="仪器校准后重传",
            entries=[{"pollutant": "SO2", "value": 600.0, "base_version": 1}],
        ),
    )
    assert response.status_code == 201
    new_exceedance = Exceedance.query.filter_by(pollutant="SO2").one()
    # 旧的"已确认"标注被清空, 按新值重新生成待标注单, 不沿用旧结论
    assert new_exceedance.status == "pending"
    assert new_exceedance.note is None
    assert new_exceedance.annotator is None
    assert new_exceedance.annotated_at is None
    assert new_exceedance.regenerated is True
    assert new_exceedance.level == "light"
    assert new_exceedance.source_version is not None
    assert new_exceedance.source_version.operator == "王敏"

    version = (
        MeasurementVersion.query.filter_by(action="overwrite")
        .order_by(MeasurementVersion.id.desc())
        .first()
    )
    assert version.previous_status == "confirmed"
    assert version.previous_annotator == "李静"
    assert version.previous_note == "现场确认属实"
    assert version.conclusion_change == "level_changed"

    # 版本回看
    measurement_id = Measurement.query.filter_by(pollutant="SO2").one().id
    history = client.get("/api/measurements/%d/versions" % measurement_id).get_json()
    assert [item["version"] for item in history["items"]] == [2, 1]
    assert history["items"][0]["action"] == "overwrite"
    assert history["items"][0]["previous_status_label"] == "已确认"


def test_concurrent_overwrite_only_one_takes_effect(client, station, entry_payload):
    client.post(
        "/api/measurements/entries",
        json=entry_payload(station.id, entries=[{"pollutant": "SO2", "value": 900.0}]),
    )

    # 双方都基于第 1 版提交: 只有一次生效, 另一侧收到 409
    first = client.post(
        "/api/measurements/entries",
        json=entry_payload(
            station.id,
            overwrite=True,
            operator="王敏",
            reason="修正 A",
            entries=[{"pollutant": "SO2", "value": 600.0, "base_version": 1}],
        ),
    )
    assert first.status_code == 201

    second = client.post(
        "/api/measurements/entries",
        json=entry_payload(
            station.id,
            overwrite=True,
            operator="赵磊",
            reason="修正 B",
            entries=[{"pollutant": "SO2", "value": 300.0, "base_version": 1}],
        ),
    )
    assert second.status_code == 409
    details = second.get_json()["error"]["details"]
    assert details["kind"] == "version_conflict"
    assert details["conflicts"][0]["current_version"] == 2

    record = Measurement.query.filter_by(pollutant="SO2").one()
    assert record.version == 2
    assert record.value == 600.0  # 先到的一方生效


def test_conclusion_changes_endpoint_lists_overwrite_impact(client, station, entry_payload):
    client.post(
        "/api/measurements/entries",
        json=entry_payload(station.id, entries=[{"pollutant": "SO2", "value": 900.0}]),
    )
    exceedance_id = Exceedance.query.one().id
    client.patch(
        "/api/exceedances/%d" % exceedance_id,
        json={"status": "ignored", "note": "校准期异常", "annotator": "李静"},
    )
    client.post(
        "/api/measurements/entries",
        json=entry_payload(
            station.id,
            overwrite=True,
            operator="王敏",
            reason="校准完成后补录",
            entries=[{"pollutant": "SO2", "value": 480.0, "base_version": 1}],
        ),
    )

    body = client.get("/api/measurements/conclusion-changes?confirmed_only=true").get_json()
    assert body["summary"]["affected_annotation_count"] == 1
    event = body["items"][0]
    assert event["pollutant"] == "SO2"
    assert event["affected_annotation"] is True
    assert event["previous_status"] == "ignored"
    assert event["operator"] == "王敏"


def test_preview_validates_without_writing(client, station, entry_payload):
    payload = entry_payload(
        station.id,
        period="daily",
        entries=[{"pollutant": "PM25", "value": 90.0}, {"pollutant": "O3", "value": 100.0}],
    )
    payload.pop("station_id")
    response = client.post("/api/measurements/preview", json=payload)
    assert response.status_code == 200
    body = response.get_json()
    assert body["summary"] == {"total": 2, "exceeded_count": 1, "exceeded_pollutants": ["PM25"]}
    assert body["results"][0]["limit"] == 75.0
    assert body["results"][0]["level"] == "light"
    assert Measurement.query.count() == 0


def test_invalid_entries_are_rejected(client, station, entry_payload):
    unknown = client.post(
        "/api/measurements/entries",
        json=entry_payload(station.id, entries=[{"pollutant": "XX", "value": 1}]),
    )
    assert unknown.status_code == 422

    non_numeric = client.post(
        "/api/measurements/entries",
        json=entry_payload(station.id, entries=[{"pollutant": "PM25", "value": "abc"}]),
    )
    assert non_numeric.status_code == 422

    empty = client.post("/api/measurements/entries", json=entry_payload(station.id, entries=[]))
    assert empty.status_code == 422

    bad_station = client.post(
        "/api/measurements/entries", json=entry_payload(9999, entries=[{"pollutant": "PM25", "value": 10}])
    )
    assert bad_station.status_code == 404


def test_hourly_particulate_is_stored_without_limit(client, station, entry_payload):
    response = client.post(
        "/api/measurements/entries",
        json=entry_payload(station.id, entries=[{"pollutant": "PM10", "value": 300.0}]),
    )
    assert response.status_code == 201
    record = Measurement.query.filter_by(pollutant="PM10").one()
    assert record.limit_value is None
    assert record.is_exceeded is False
    assert Exceedance.query.count() == 0


def test_list_measurements_with_filters(client, station, entry_payload):
    client.post("/api/measurements/entries", json=entry_payload(station.id))
    body = client.get("/api/measurements?station_id=%d&pollutant=SO2" % station.id).get_json()
    assert body["total"] == 1
    assert body["items"][0]["pollutant_label"] == "SO₂"
    assert body["items"][0]["station"]["code"] == "TEST-001"
    assert body["summary"]["exceeded_count"] == 1

    exceeded = client.get("/api/measurements?is_exceeded=true").get_json()
    assert exceeded["total"] == 1


def test_delete_measurement_removes_exceedance(client, station, entry_payload):
    created = client.post("/api/measurements/entries", json=entry_payload(station.id)).get_json()
    exceeded_id = created["exceedances"][0]["measurement_id"]
    response = client.delete("/api/measurements/%d" % exceeded_id)
    assert response.status_code == 200
    assert Exceedance.query.count() == 0
    assert Measurement.query.count() == 2


def test_entry_context_exposes_form_options(client, station):
    body = client.get("/api/measurements/entry-context").get_json()
    assert body["stations"][0]["code"] == "TEST-001"
    assert {item["value"] for item in body["periods"]} == {"hourly", "daily"}
    assert {item["value"] for item in body["data_sources"]} >= {"manual", "device"}


def test_export_measurements_csv(client, station, entry_payload):
    client.post("/api/measurements/entries", json=entry_payload(station.id))
    response = client.get("/api/measurements/export?station_id=%d" % station.id)
    assert response.status_code == 200
    assert "text/csv" in response.headers["Content-Type"]
    text = response.get_data(as_text=True)
    assert text.startswith("\ufeff站点编码")
    assert "测试监测点" in text
    assert len([line for line in text.strip().splitlines()]) == 4
