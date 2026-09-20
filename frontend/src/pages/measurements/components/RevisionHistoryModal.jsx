import { useCallback } from 'react'
import { listMeasurementRevisions } from '../../../api/measurements.js'
import Modal from '../../../components/common/Modal.jsx'
import Tag from '../../../components/common/Tag.jsx'
import { ErrorState, Loading } from '../../../components/common/Feedback.jsx'
import { EXCEEDANCE_LEVEL_TONE } from '../../../constants/index.js'
import { useAsyncData } from '../../../hooks/useAsyncData.js'
import { formatDateTime, formatNumber, formatRatio } from '../../../utils/format.js'

function ConclusionCell({ exceeded, ratio, level, levelLabel }) {
  if (!exceeded) return <Tag tone="success">达标</Tag>
  return (
    <Tag tone={EXCEEDANCE_LEVEL_TONE[level] || 'danger'}>
      {formatRatio(ratio)}
      {levelLabel ? ` · ${levelLabel}` : ''}
    </Tag>
  )
}

/** 单条监测数据的覆盖版本历史: 按版本号倒序回看每次覆盖的新旧对照与操作留痕。 */
export default function RevisionHistoryModal({ measurement, onClose }) {
  const loader = useCallback(
    () => listMeasurementRevisions(measurement.id),
    [measurement?.id]
  )
  const { data, loading, error } = useAsyncData(loader, { immediate: Boolean(measurement) })

  return (
    <Modal
      open={Boolean(measurement)}
      wide
      title={
        measurement
          ? `覆盖版本历史 · ${measurement.station?.name || ''} ${measurement.pollutant_label}`
          : '覆盖版本历史'
      }
      onClose={onClose}
    >
      {loading && !data ? <Loading text="正在加载版本历史..." /> : null}
      {error && !data ? <ErrorState error={error} /> : null}
      {data ? (
        <div className="stack">
          <div className="small muted">
            当前为第 {data.measurement.version} 版, 监测时间{' '}
            {formatDateTime(data.measurement.measured_at)} · {data.measurement.period_label};
            共 {data.total} 次覆盖, 按版本倒序展示。
          </div>
          {data.items.length === 0 ? (
            <div className="empty">该记录尚未发生过覆盖</div>
          ) : (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>版本</th>
                    <th className="text-right">数值变化</th>
                    <th>判定变化</th>
                    <th>被重置的原标注</th>
                    <th>操作人 / 原因</th>
                    <th>覆盖时间</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((item) => (
                    <tr key={item.id}>
                      <td className="cell-nowrap">
                        <Tag tone="primary">v{item.version}</Tag>
                      </td>
                      <td className="text-right cell-nowrap">
                        <span className="muted">{formatNumber(item.old_value)}</span>
                        <span className="muted"> → </span>
                        <span className="strong">{formatNumber(item.new_value)}</span>{' '}
                        <span className="muted small">{item.unit || ''}</span>
                        <div className="small">
                          <span className={item.value_diff > 0 ? 'danger-text' : 'success-text'}>
                            {item.value_diff > 0 ? '+' : ''}
                            {formatNumber(item.value_diff)}
                          </span>
                        </div>
                      </td>
                      <td className="cell-nowrap">
                        <ConclusionCell
                          exceeded={item.old_is_exceeded}
                          ratio={item.old_exceed_ratio}
                          level={item.old_level}
                          levelLabel={item.old_level_label}
                        />
                        <span className="muted"> → </span>
                        <ConclusionCell
                          exceeded={item.new_is_exceeded}
                          ratio={item.new_exceed_ratio}
                          level={item.new_level}
                          levelLabel={item.new_level_label}
                        />
                        {item.conclusion_changed ? (
                          <div className="small danger-text">结论变化</div>
                        ) : null}
                      </td>
                      <td>
                        {item.prev_annotation_status &&
                        item.prev_annotation_status !== 'pending' ? (
                          <div className="small">
                            <Tag tone="warning">{item.prev_annotation_status_label}</Tag>{' '}
                            {item.prev_annotator || '未署名'}
                            {item.prev_note ? (
                              <div className="muted" style={{ maxWidth: 220 }}>
                                {item.prev_note}
                              </div>
                            ) : null}
                          </div>
                        ) : (
                          <span className="muted small">无</span>
                        )}
                      </td>
                      <td>
                        <div className="small strong">{item.operator}</div>
                        <div className="small muted" style={{ maxWidth: 220 }}>
                          {item.reason}
                        </div>
                      </td>
                      <td className="cell-nowrap">{formatDateTime(item.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ) : null}
    </Modal>
  )
}
