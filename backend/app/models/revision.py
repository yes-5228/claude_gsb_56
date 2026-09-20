"""监测数据覆盖版本: 每次覆盖留下一条新旧对照快照, 支撑按时间回看与结论溯源."""
from datetime import datetime

from ..domain.constants import EXCEEDANCE_LEVEL_LABELS, EXCEEDANCE_STATUS_LABELS, label_of
from ..extensions import db
from .base import iso


class MeasurementRevision(db.Model):
    __tablename__ = "measurement_revisions"
    __table_args__ = (
        db.UniqueConstraint("measurement_id", "version", name="uq_revision_measurement_version"),
    )

    id = db.Column(db.Integer, primary_key=True)
    measurement_id = db.Column(
        db.Integer,
        db.ForeignKey("measurements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version = db.Column(db.Integer, nullable=False)
    old_value = db.Column(db.Float, nullable=False)
    new_value = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(16))
    old_limit_value = db.Column(db.Float)
    new_limit_value = db.Column(db.Float)
    old_is_exceeded = db.Column(db.Boolean, nullable=False, default=False)
    new_is_exceeded = db.Column(db.Boolean, nullable=False, default=False)
    old_exceed_ratio = db.Column(db.Float)
    new_exceed_ratio = db.Column(db.Float)
    old_level = db.Column(db.String(16))
    new_level = db.Column(db.String(16))
    # 覆盖前超标记录上的人工标注快照 (重算后被重置, 仅在此留痕)
    prev_annotation_status = db.Column(db.String(16))
    prev_annotator = db.Column(db.String(64))
    prev_note = db.Column(db.Text)
    prev_annotated_at = db.Column(db.DateTime)
    operator = db.Column(db.String(64), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False, index=True)

    measurement = db.relationship("Measurement", back_populates="revisions")

    def conclusion_changed(self):
        """覆盖前后超标结论是否发生变化 (超标与否或等级变化)."""
        return bool(self.old_is_exceeded) != bool(self.new_is_exceeded) or (
            self.old_level or None
        ) != (self.new_level or None)

    def to_dict(self, include_measurement=False):
        payload = {
            "id": self.id,
            "measurement_id": self.measurement_id,
            "version": self.version,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "value_diff": round(float(self.new_value) - float(self.old_value), 6),
            "unit": self.unit,
            "old_limit_value": self.old_limit_value,
            "new_limit_value": self.new_limit_value,
            "old_is_exceeded": bool(self.old_is_exceeded),
            "new_is_exceeded": bool(self.new_is_exceeded),
            "old_exceed_ratio": self.old_exceed_ratio,
            "new_exceed_ratio": self.new_exceed_ratio,
            "old_level": self.old_level,
            "old_level_label": label_of(EXCEEDANCE_LEVEL_LABELS, self.old_level)
            if self.old_level
            else None,
            "new_level": self.new_level,
            "new_level_label": label_of(EXCEEDANCE_LEVEL_LABELS, self.new_level)
            if self.new_level
            else None,
            "conclusion_changed": self.conclusion_changed(),
            "prev_annotation_status": self.prev_annotation_status,
            "prev_annotation_status_label": label_of(
                EXCEEDANCE_STATUS_LABELS, self.prev_annotation_status
            )
            if self.prev_annotation_status
            else None,
            "prev_annotator": self.prev_annotator,
            "prev_note": self.prev_note,
            "prev_annotated_at": iso(self.prev_annotated_at),
            "operator": self.operator,
            "reason": self.reason,
            "created_at": iso(self.created_at),
        }
        if include_measurement and self.measurement:
            payload["measurement"] = self.measurement.to_dict(include_station=True)
        return payload

    def __repr__(self):
        return "<MeasurementRevision measurement=%s v%s>" % (self.measurement_id, self.version)
