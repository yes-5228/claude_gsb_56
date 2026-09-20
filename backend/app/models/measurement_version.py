"""监测数据版本快照.

每一次新增 / 覆盖 / 删除监测数据都会追加一条不可变快照, 用于:

- 按时间回看同一条监测数据的历次取值与超标结论;
- 记录覆盖操作的操作人与原因;
- 当覆盖改变了已标注的超标结论时, 保留旧结论与旧标注, 标明是哪一次覆盖导致结论变化。
"""
from datetime import datetime

from ..domain.constants import (
    DATA_SOURCE_LABELS,
    EXCEEDANCE_LEVEL_LABELS,
    EXCEEDANCE_STATUS_LABELS,
    PERIOD_LABELS,
    label_of,
)
from ..extensions import db
from .base import iso

# 版本动作
ACTION_CREATE = "create"
ACTION_OVERWRITE = "overwrite"
ACTION_DELETE = "delete"

ACTION_LABELS = {
    ACTION_CREATE: "首次录入",
    ACTION_OVERWRITE: "覆盖更新",
    ACTION_DELETE: "删除",
}

# 覆盖前后超标结论的变化类型
CONCLUSION_UNCHANGED = "unchanged"
CONCLUSION_EXCEEDED_TO_NORMAL = "exceeded_to_normal"   # 原超标 -> 新值达标/撤销
CONCLUSION_NORMAL_TO_EXCEEDED = "normal_to_exceeded"   # 原达标/无单 -> 新值超标
CONCLUSION_LEVEL_CHANGED = "level_changed"             # 仍超标, 等级/倍数变化

CONCLUSION_CHANGE_LABELS = {
    CONCLUSION_UNCHANGED: "结论不变",
    CONCLUSION_EXCEEDED_TO_NORMAL: "超标撤销",
    CONCLUSION_NORMAL_TO_EXCEEDED: "新增超标",
    CONCLUSION_LEVEL_CHANGED: "超标程度变化",
}


def classify_conclusion_change(before, after):
    """对比覆盖前后的判定结果, 得出结论变化类型.

    ``before`` / ``after`` 为 exceedance_rules.evaluate 的返回值。
    """
    if bool(before.get("exceeded")) != bool(after.get("exceeded")):
        return (
            CONCLUSION_EXCEEDED_TO_NORMAL
            if before.get("exceeded")
            else CONCLUSION_NORMAL_TO_EXCEEDED
        )
    if before.get("exceeded") and before.get("level") != after.get("level"):
        return CONCLUSION_LEVEL_CHANGED
    return CONCLUSION_UNCHANGED


class MeasurementVersion(db.Model):
    __tablename__ = "measurement_versions"

    id = db.Column(db.Integer, primary_key=True)
    measurement_id = db.Column(
        db.Integer,
        db.ForeignKey("measurements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    station_id = db.Column(
        db.Integer, db.ForeignKey("stations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(16), nullable=False)

    # 该版本生效时刻的监测数据快照
    pollutant = db.Column(db.String(16), nullable=False, index=True)
    period = db.Column(db.String(16), nullable=False)
    value = db.Column(db.Float)
    unit = db.Column(db.String(16))
    limit_value = db.Column(db.Float)
    exceed_ratio = db.Column(db.Float)
    is_exceeded = db.Column(db.Boolean, nullable=False, default=False)
    level = db.Column(db.String(16))
    measured_at = db.Column(db.DateTime, nullable=False, index=True)
    data_source = db.Column(db.String(16))
    recorder = db.Column(db.String(64))
    remark = db.Column(db.Text)

    # 覆盖审计 (action=overwrite 时必填)
    operator = db.Column(db.String(64))
    reason = db.Column(db.Text)

    # 覆盖时被替换掉的旧值与旧结论
    previous_value = db.Column(db.Float)
    previous_is_exceeded = db.Column(db.Boolean)
    previous_level = db.Column(db.String(16))
    previous_exceed_ratio = db.Column(db.Float)
    conclusion_change = db.Column(db.String(32))

    # 覆盖前超标单上的人工标注 (归档, 用于追溯"结论是被哪次覆盖改掉的")
    previous_status = db.Column(db.String(16))
    previous_annotator = db.Column(db.String(64))
    previous_annotated_at = db.Column(db.DateTime)
    previous_note = db.Column(db.Text)
    previous_exceedance_id = db.Column(db.Integer)

    operated_at = db.Column(db.DateTime, nullable=False, default=datetime.now, index=True)

    measurement = db.relationship("Measurement", back_populates="versions")

    def _labels(self):
        return {
            "pollutant": self.pollutant,
            "pollutant_label": self.measurement.pollutant_label()
            if self.measurement
            else self.pollutant,
        }

    def to_dict(self):
        labels = self._labels()
        return {
            "id": self.id,
            "measurement_id": self.measurement_id,
            "station_id": self.station_id,
            "version": self.version,
            "action": self.action,
            "action_label": ACTION_LABELS.get(self.action, self.action),
            "pollutant": labels["pollutant"],
            "pollutant_label": labels["pollutant_label"],
            "period": self.period,
            "period_label": label_of(PERIOD_LABELS, self.period),
            "value": self.value,
            "unit": self.unit,
            "limit_value": self.limit_value,
            "exceed_ratio": self.exceed_ratio,
            "is_exceeded": bool(self.is_exceeded),
            "level": self.level,
            "level_label": label_of(EXCEEDANCE_LEVEL_LABELS, self.level) if self.level else None,
            "measured_at": iso(self.measured_at),
            "data_source": self.data_source,
            "data_source_label": label_of(DATA_SOURCE_LABELS, self.data_source),
            "recorder": self.recorder,
            "remark": self.remark,
            "operator": self.operator,
            "reason": self.reason,
            "previous_value": self.previous_value,
            "previous_is_exceeded": (
                bool(self.previous_is_exceeded) if self.previous_is_exceeded is not None else None
            ),
            "previous_level": self.previous_level,
            "previous_level_label": (
                label_of(EXCEEDANCE_LEVEL_LABELS, self.previous_level)
                if self.previous_level
                else None
            ),
            "previous_exceed_ratio": self.previous_exceed_ratio,
            "conclusion_change": self.conclusion_change,
            "conclusion_change_label": (
                label_of(CONCLUSION_CHANGE_LABELS, self.conclusion_change)
                if self.conclusion_change
                else None
            ),
            "previous_status": self.previous_status,
            "previous_status_label": (
                label_of(EXCEEDANCE_STATUS_LABELS, self.previous_status)
                if self.previous_status
                else None
            ),
            "previous_annotator": self.previous_annotator,
            "previous_annotated_at": iso(self.previous_annotated_at),
            "previous_note": self.previous_note,
            "previous_exceedance_id": self.previous_exceedance_id,
            "operated_at": iso(self.operated_at),
        }

    def __repr__(self):
        return "<MeasurementVersion m=%s v=%s %s>" % (
            self.measurement_id,
            self.version,
            self.action,
        )
