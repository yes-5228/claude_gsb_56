"""超标记录 (含人工标注)."""
from ..domain.constants import (
    EXCEEDANCE_LEVEL_LABELS,
    EXCEEDANCE_STATUS_LABELS,
    PERIOD_LABELS,
    label_of,
)
from ..extensions import db
from .base import TimestampMixin, iso


class Exceedance(TimestampMixin, db.Model):
    __tablename__ = "exceedances"

    id = db.Column(db.Integer, primary_key=True)
    measurement_id = db.Column(
        db.Integer,
        db.ForeignKey("measurements.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    station_id = db.Column(
        db.Integer, db.ForeignKey("stations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pollutant = db.Column(db.String(16), nullable=False, index=True)
    period = db.Column(db.String(16), nullable=False, default="hourly")
    value = db.Column(db.Float, nullable=False)
    limit_value = db.Column(db.Float, nullable=False)
    exceed_ratio = db.Column(db.Float, nullable=False)
    level = db.Column(db.String(16), nullable=False, default="light", index=True)
    status = db.Column(db.String(16), nullable=False, default="pending", index=True)
    note = db.Column(db.Text)
    annotator = db.Column(db.String(64))
    annotated_at = db.Column(db.DateTime)
    measured_at = db.Column(db.DateTime, nullable=False, index=True)

    # 结论来源: 该超标单(重新)生成时对应的监测数据版本;
    # 覆盖导致结论重算后, 指向最近一次覆盖版本, 旧标注不再沿用。
    source_version_id = db.Column(
        db.Integer,
        db.ForeignKey("measurement_versions.id", ondelete="SET NULL"),
    )
    # True 表示本单是覆盖重算后重新生成的(历史上曾有被覆盖掉的旧结论)
    regenerated = db.Column(db.Boolean, nullable=False, default=False)

    measurement = db.relationship("Measurement", back_populates="exceedance")
    station = db.relationship("Station", back_populates="exceedances")
    source_version = db.relationship("MeasurementVersion", foreign_keys=[source_version_id])

    def to_dict(self, include_relations=False):
        payload = {
            "id": self.id,
            "measurement_id": self.measurement_id,
            "station_id": self.station_id,
            "pollutant": self.pollutant,
            "pollutant_label": self.measurement.pollutant_label() if self.measurement else self.pollutant,
            "period": self.period,
            "period_label": label_of(PERIOD_LABELS, self.period),
            "value": self.value,
            "limit_value": self.limit_value,
            "exceed_ratio": self.exceed_ratio,
            "level": self.level,
            "level_label": label_of(EXCEEDANCE_LEVEL_LABELS, self.level),
            "status": self.status,
            "status_label": label_of(EXCEEDANCE_STATUS_LABELS, self.status),
            "note": self.note,
            "annotator": self.annotator,
            "annotated_at": iso(self.annotated_at),
            "measured_at": iso(self.measured_at),
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
            "station_name": self.station.name if self.station else None,
            "station_code": self.station.code if self.station else None,
            "unit": self.measurement.unit if self.measurement else None,
            "regenerated": bool(self.regenerated),
            "source_version": self._source_version_payload(),
        }
        if include_relations and self.measurement:
            payload["measurement"] = self.measurement.to_dict(include_station=True)
        return payload

    def _source_version_payload(self):
        version = self.source_version
        if version is None:
            return None
        return {
            "id": version.id,
            "version": version.version,
            "operator": version.operator,
            "reason": version.reason,
            "operated_at": iso(version.operated_at),
            "conclusion_change": version.conclusion_change,
        }

    def __repr__(self):
        return "<Exceedance %s %s %.2f>" % (self.station_id, self.pollutant, self.value)
