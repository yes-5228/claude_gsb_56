import { useCallback } from 'react'
import { listMeasurementVersions } from '../../../api/measurements.js'
import Modal from '../../../components/common/Modal.jsx'
import { Alert, ErrorState, Loading } from '../../../components/common/Feedback.jsx'
import Tag from '../../../components/common/Tag.jsx'
import { useAsyncData } from '../../../hooks/useAsyncData.js'
import {
  EXCEEDANCE_LEVEL_LABELS,
  EXCEEDANCE_LEVEL_TONE,
  EXCEEDANCE_STATUS_TONE
} from '../../../constants/index.js'
import { formatDateTime, formatNumber, formatRatio } from '../../../utils/format.js'

const ACTION_TONE = { create: 'info', overwrite: 'warning', delete: 'neutral' }
const CHANGE_TONE = {
  unchanged: 'neutral',
  exceeded_to_normal: 'success',
  normal_to_exceeded: 'danger',
  level_changed: 'warning'
}

function ConclusionBadge({ isExceeded, level, ratio }) {
  if (!isExceeded) return <Tag tone="success">达标</Tag>
  return (
    <span className="inline" style={{ gap: 4 }}>
      <Tag tone="danger">超标 {formatRatio(ratio)}</Tag>
      <Tag tone={EXCEEDANCE_LEVEL_TONE[level]}>{EXCEEDANCE_LEVEL_LABELS[level] || level}</Tag>
    </span>
  )
}

export default function VersionHistoryDrawer({ measurementId, onClose }) {
  const loader = useCallback(() => listMeasurementVersions(measurementId), [measurementId])
  const { data, loading, error } = useAsyncData(loader, { immediate: Boolean(measurementId) })

  return (
    <Modal
      open={Boolean(measurementId)}
      drawer
      title="监测数据版本历史"
      onClose={onClose}
      footer={
        <button type="button" className="btn" onClick={onClose}>
          关闭
        </button>
      }
    >
      {loading && !data ? <Loading /> : null}
      {error && !data ? <ErrorState error={error} /> : null}
      {data ? (
        <div className="stack">
          <div className="card" style={{ boxShadow: 'none' }}>
            <div className="card-body tight">
              <div className="strong">
                {data.measurement.pollutant_label} · {formatDateTime(data.measurement.measured_at)}
              </div>
              <div className="small muted">
                当前为第 {data.measurement.current_version} 版, 值 {formatNumber(data.measurement.current_value)}{' '}
                {data.measurement.unit}, 共修订 {data.measurement.current_version - 1} 次
              </div>
            </div>
          </div>

          <div className="timeline">
            {data.items.map((version) => (
              <div key={version.id} className="timeline-item">
                <div className="timeline-dot">v{version.version}</div>
                <div className="timeline-content card">
                  <div className="card-body tight stack">
                    <div className="inline" style={{ justifyContent: 'space-between' }}>
                      <Tag tone={ACTION_TONE[version.action] || 'neutral'}>
                        {version.action_label}
                      </Tag>
                      <span className="small muted">{formatDateTime(version.operated_at)}</span>
                    </div>

                    <div className="inline" style={{ gap: 12 }}>
                      <span>
                        数值: <span className="strong">{formatNumber(version.value)}</span>{' '}
                        <span className="muted small">{version.unit}</span>
                      </span>
                      <ConclusionBadge
                        isExceeded={version.is_exceeded}
                        level={version.level}
                        ratio={version.exceed_ratio}
                      />
                    </div>

                    {version.action === 'overwrite' ? (
                      <>
                        <dl className="kv">
                          <dt>原值</dt>
                          <dd>
                            {formatNumber(version.previous_value)} {version.unit}
                            <span className="muted small"> → {formatNumber(version.value)}</span>
                          </dd>
                          <dt>操作人</dt>
                          <dd>{version.operator}</dd>
                          <dt>覆盖原因</dt>
                          <dd>{version.reason}</dd>
                          <dt>结论变化</dt>
                          <dd>
                            <Tag tone={CHANGE_TONE[version.conclusion_change] || 'neutral'}>
                              {version.conclusion_change_label}
                            </Tag>
                          </dd>
                        </dl>

                        {version.previous_status ? (
                          <Alert tone="warning">
                            本次覆盖作废了原「{version.previous_status_label}」标注
                            {version.previous_annotator ? ` (${version.previous_annotator})` : ''}
                            {version.previous_annotated_at
                              ? ` · ${formatDateTime(version.previous_annotated_at)}`
                              : ''}
                            , 原说明: {version.previous_note || '无'}
                          </Alert>
                        ) : null}
                        {version.previous_is_exceeded && !version.is_exceeded ? (
                          <Alert tone="info">原超标结论随新值撤销。</Alert>
                        ) : null}
                      </>
                    ) : (
                      <div className="small muted">
                        录入人: {version.recorder || '-'}
                        {version.remark ? ` · ${version.remark}` : ''}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </Modal>
  )
}
