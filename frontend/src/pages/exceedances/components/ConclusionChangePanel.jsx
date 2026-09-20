import { SectionCard } from '../../../components/common/Card.jsx'
import { ErrorState, Loading } from '../../../components/common/Feedback.jsx'
import Tag from '../../../components/common/Tag.jsx'
import { useAsyncData } from '../../../hooks/useAsyncData.js'
import { listConclusionChanges } from '../../../api/measurements.js'
import { formatDateTime, formatNumber } from '../../../utils/format.js'

const CHANGE_TONE = {
  exceeded_to_normal: 'success',
  normal_to_exceeded: 'danger',
  level_changed: 'warning'
}

export default function ConclusionChangePanel({ onShowMeasurement }) {
  const { data, loading, error, reload } = useAsyncData(() =>
    listConclusionChanges({ confirmed_only: true })
  )

  const items = data?.items ?? []

  return (
    <SectionCard
      title="覆盖导致的结论变更追溯"
      hint="列出覆盖了已有确认/忽略标注的操作, 标明超标结论是被哪一次覆盖改掉的"
      actions={
        <button type="button" className="btn btn-sm" onClick={reload} disabled={loading}>
          刷新
        </button>
      }
    >
      {loading && !data ? <Loading /> : null}
      {error ? <ErrorState error={error} /> : null}
      {data && items.length === 0 ? (
        <div className="empty">暂无覆盖改变已标注结论的记录</div>
      ) : null}
      {items.length ? (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>覆盖时间</th>
                <th>监测点 / 因子</th>
                <th>监测时刻</th>
                <th>原值 → 新值</th>
                <th>结论变化</th>
                <th>被覆盖的标注</th>
                <th>覆盖操作人 / 原因</th>
                <th>版本</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td className="cell-nowrap">{formatDateTime(item.operated_at)}</td>
                  <td className="cell-nowrap">
                    <div>{item.station_name}</div>
                    <div className="small muted mono">{item.station_code}</div>
                    <div>{item.pollutant_label}</div>
                  </td>
                  <td className="cell-nowrap">{formatDateTime(item.measured_at)}</td>
                  <td className="cell-nowrap">
                    <span className={item.previous_is_exceeded ? 'danger-text' : ''}>
                      {formatNumber(item.previous_value)}
                    </span>
                    {' → '}
                    <span className="strong">{formatNumber(item.value)}</span>
                    <span className="muted small"> {item.unit}</span>
                  </td>
                  <td className="cell-nowrap">
                    <Tag tone={CHANGE_TONE[item.conclusion_change] || 'neutral'}>
                      {item.conclusion_change_label}
                    </Tag>
                  </td>
                  <td>
                    <Tag tone={item.previous_status === 'confirmed' ? 'danger' : 'neutral'}>
                      原{item.previous_status_label}
                    </Tag>
                    <div className="small muted">
                      {item.previous_annotator || '-'} · {formatDateTime(item.previous_annotated_at)}
                    </div>
                    <div className="small">{item.previous_note}</div>
                  </td>
                  <td style={{ maxWidth: 240 }}>
                    <div className="strong">{item.operator}</div>
                    <div className="small">{item.reason}</div>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={() => onShowMeasurement?.(item.measurement_id)}
                    >
                      v{item.version}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </SectionCard>
  )
}
