import { SectionCard } from '../../../components/common/Card.jsx'
import { Alert } from '../../../components/common/Feedback.jsx'
import Tag from '../../../components/common/Tag.jsx'
import { EXCEEDANCE_LEVEL_LABELS, EXCEEDANCE_LEVEL_TONE } from '../../../constants/index.js'
import { formatDateTime, formatNumber, formatPercent } from '../../../utils/format.js'

function ResultTable({ columns, rows }) {
  if (rows.length === 0) return <div className="empty">没有数据</div>
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key}>{column.title}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key}>
              {columns.map((column) => (
                <td key={column.key}>{column.render(row)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function EntryResultPanel({ result, summary, onClose }) {
  if (!result) {
    return (
      <SectionCard
        title="录入结果概览"
        hint="提交后在此确认写入结果与超标判定, 也可先做超标校验预览"
      >
        {summary ? (
          <div className="stack">
            <div className="stat-grid">
              <div className="stat-card">
                <div className="stat-label">当前筛选记录数</div>
                <div className="stat-value">{summary.total}</div>
              </div>
              <div className="stat-card">
                <div className="stat-label">其中超标</div>
                <div className="stat-value danger-text">{summary.exceeded_count}</div>
                <div className="stat-foot">超标率 {formatPercent(summary.exceed_rate)}</div>
              </div>
              <div className="stat-card">
                <div className="stat-label">涉及监测点</div>
                <div className="stat-value">{summary.station_count}</div>
              </div>
            </div>
            <dl className="kv">
              <dt>最早监测时间</dt>
              <dd>{formatDateTime(summary.first_measured_at)}</dd>
              <dt>最近监测时间</dt>
              <dd>{formatDateTime(summary.last_measured_at)}</dd>
              <dt>均值</dt>
              <dd>{formatNumber(summary.avg_value)}</dd>
            </dl>
          </div>
        ) : (
          <div className="empty">提交数据后这里会展示写入结果</div>
        )}
      </SectionCard>
    )
  }

  const payload = result.payload
  const isPreview = result.kind === 'preview'
  const rows = isPreview
    ? (payload.results || []).map((item) => ({
        key: item.pollutant,
        ...item
      }))
    : (payload.evaluations || []).map((item) => ({ key: item.pollutant, ...item }))

  const columns = [
    { key: 'pollutant', title: '监测因子', render: (row) => row.pollutant_label || row.pollutant },
    { key: 'value', title: '监测值', render: (row) => `${formatNumber(row.value)} ${row.unit || ''}` },
    {
      key: 'limit',
      title: '限值',
      render: (row) => (row.limit === null || row.limit === undefined ? '无限值' : formatNumber(row.limit))
    },
    {
      key: 'exceeded',
      title: '判定',
      render: (row) =>
        row.exceeded ? (
          <Tag tone="danger">超标 {formatNumber(row.ratio, 2)} 倍</Tag>
        ) : row.applicable ? (
          <Tag tone="success">达标</Tag>
        ) : (
          <Tag tone="neutral">仅记录</Tag>
        )
    },
    {
      key: 'level',
      title: '等级',
      render: (row) =>
        row.level ? (
          <Tag tone={EXCEEDANCE_LEVEL_TONE[row.level]}>
            {row.level_label || EXCEEDANCE_LEVEL_LABELS[row.level] || row.level}
          </Tag>
        ) : (
          '-'
        )
    }
  ]

  return (
    <SectionCard
      title={isPreview ? '超标校验预览 (未写库)' : '录入结果'}
      hint={
        isPreview
          ? '仅做判定预览, 数据尚未保存'
          : `写入时间 ${formatDateTime(new Date().toISOString())}`
      }
      actions={
        <button type="button" className="btn btn-sm" onClick={onClose}>
          关闭
        </button>
      }
    >
      <div className="stack">
        {isPreview ? (
          <Alert tone={payload.summary.exceeded_count ? 'warning' : 'success'}>
            共校验 {payload.summary.total} 个因子, 其中 {payload.summary.exceeded_count} 个超过限值
            {payload.summary.exceeded_pollutants.length
              ? `: ${payload.summary.exceeded_pollutants.join(', ')}`
              : ''}
          </Alert>
        ) : (
          <div className="stat-grid">
            <div className="stat-card">
              <div className="stat-label">新增</div>
              <div className="stat-value success-text">{payload.summary.created_count}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">更新</div>
              <div className="stat-value">{payload.summary.updated_count}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">超标</div>
              <div className="stat-value danger-text">{payload.summary.exceeded_count}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">跳过重复</div>
              <div className="stat-value" style={{ color: 'var(--warning)' }}>
                {payload.summary.duplicate_count}
              </div>
            </div>
          </div>
        )}

        <ResultTable columns={columns} rows={rows} />

        {payload.duplicates?.length ? (
          <Alert tone="warning">
            以下因子在该时刻已存在数据, 已跳过保留原值: {payload.duplicates.map((item) => item.pollutant_label).join(', ')}
          </Alert>
        ) : null}

        {payload.conclusion_changes?.length ? (
          <div className="stack">
            <Alert tone="warning">
              本次覆盖中有 {payload.summary?.conclusion_changed_count ?? payload.conclusion_changes.length} 项超标结论发生变化, 均已按新值重新判定; 原有标注不再沿用。
            </Alert>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>因子</th>
                    <th>原值 → 新值</th>
                    <th>结论变化</th>
                    <th>覆盖操作人</th>
                    <th>覆盖原因</th>
                  </tr>
                </thead>
                <tbody>
                  {payload.conclusion_changes.map((change) => (
                    <tr key={change.pollutant}>
                      <td>{change.pollutant_label}</td>
                      <td className="cell-nowrap">
                        <span className="muted">{formatNumber(change.old_value)}</span>
                        {' → '}
                        <span className="strong">{formatNumber(change.new_value)}</span>
                      </td>
                      <td>
                        <Tag tone={change.conclusion_change === 'exceeded_to_normal' ? 'success' : 'danger'}>
                          {change.conclusion_change === 'exceeded_to_normal'
                            ? '超标撤销'
                            : change.conclusion_change === 'normal_to_exceeded'
                              ? '新增超标'
                              : '超标程度变化'}
                        </Tag>
                        {change.annotation_reset ? (
                          <div className="small muted">原确认/忽略标注已重置为待标注</div>
                        ) : null}
                      </td>
                      <td>{change.operator}</td>
                      <td style={{ maxWidth: 260 }}>{change.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}

        {payload.exceedances?.length ? (
          <Alert tone="warning">
            本次生成 {payload.exceedances.length} 条待标注超标记录, 请前往“超标记录标注”模块复核。
          </Alert>
        ) : null}
      </div>
    </SectionCard>
  )
}
