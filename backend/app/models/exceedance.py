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
    # 指向导致本次标注被重置的那一次数据覆盖 (重算溯源)
    reset_by_revision_id = db.Column(
        db.Integer, db.ForeignKey("measurement_revisions.id", ondelete="SET NULL"), nullable=True
    )

    measurement = db.relationship("Measurement", back_populates="exceedance")
    station = db.relationship("Station", back_populates="exceedances")
    reset_by_revision = db.relationship("MeasurementRevision")

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
            "reset_by_revision": self._reset_by_revision_payload(),
        }
        if include_relations and self.measurement:
            payload["measurement"] = self.measurement.to_dict(include_station=True)
        return payload

    def _reset_by_revision_payload(self):
        """摘要信息: 哪一次覆盖把已标注结论重置回待标注."""
        revision = self.reset_by_revision
        if revision is None:
            return None
        return {
            "id": revision.id,
            "version": revision.version,
            "operator": revision.operator,
            "reason": revision.reason,
            "created_at": iso(revision.created_at),
            "old_value": revision.old_value,
            "new_value": revision.new_value,
            "unit": revision.unit,
            "prev_annotation_status": revision.prev_annotation_status,
            "prev_annotation_status_label": label_of(
                EXCEEDANCE_STATUS_LABELS, revision.prev_annotation_status
            )
            if revision.prev_annotation_status
            else None,
            "prev_annotator": revision.prev_annotator,
            "prev_note": revision.prev_note,
        }

    def __repr__(self):
        return "<Exceedance %s %s %.2f>" % (self.station_id, self.pollutant, self.value)
