import { useEffect } from 'react'
import { listRevisions } from '../../../api/measurements.js'
import DataTable from '../../../components/common/DataTable.jsx'
import Pagination from '../../../components/common/Pagination.jsx'
import Tag from '../../../components/common/Tag.jsx'
import { Alert } from '../../../components/common/Feedback.jsx'
import { EXCEEDANCE_LEVEL_TONE } from '../../../constants/index.js'
import { useListQuery } from '../../../hooks/useListQuery.js'
import { formatDateTime, formatNumber, formatRatio } from '../../../utils/format.js'

function ConclusionTag({ exceeded, ratio, level, levelLabel }) {
  if (!exceeded) return <Tag tone="success">达标</Tag>
  return (
    <Tag tone={EXCEEDANCE_LEVEL_TONE[level] || 'danger'}>
      {formatRatio(ratio)}
      {levelLabel ? ` · ${levelLabel}` : ''}
    </Tag>
  )
}

/** 全部覆盖版本按时间倒序回看, 复用列表页的监测点/因子/时间筛选条件。 */
export default function RevisionListPanel({ filters }) {
  const query = useListQuery(listRevisions, {})

  useEffect(() => {
    query.setFilters({
      station_id: filters.station_id,
      pollutant: filters.pollutant,
      date_from: filters.date_from,
      date_to: filters.date_to
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters])

  const columns = [
    {
      key: 'created_at',
      title: '覆盖时间',
      className: 'cell-nowrap',
      render: (row) => formatDateTime(row.created_at)
    },
    {
      key: 'station',
      title: '监测点 / 因子',
      render: (row) => (
        <div>
          <div>{row.measurement?.station?.name || '-'}</div>
          <div className="small muted">
            {row.measurement?.pollutant_label} · {row.measurement?.period_label} · 监测时间{' '}
            {formatDateTime(row.measurement?.measured_at)}
          </div>
        </div>
      )
    },
    {
      key: 'version',
      title: '版本',
      className: 'cell-nowrap',
      render: (row) => <Tag tone="primary">v{row.version}</Tag>
    },
    {
      key: 'value',
      title: '数值变化',
      align: 'right',
      className: 'cell-nowrap',
      render: (row) => (
        <span>
          <span className="muted">{formatNumber(row.old_value)}</span>
          <span className="muted"> → </span>
          <span className="strong">{formatNumber(row.new_value)}</span>{' '}
          <span className="muted small">{row.unit || ''}</span>
        </span>
      )
    },
    {
      key: 'conclusion',
      title: '判定变化',
      className: 'cell-nowrap',
      render: (row) => (
        <span>
          <ConclusionTag
            exceeded={row.old_is_exceeded}
            ratio={row.old_exceed_ratio}
            level={row.old_level}
            levelLabel={row.old_level_label}
          />
          <span className="muted"> → </span>
          <ConclusionTag
            exceeded={row.new_is_exceeded}
            ratio={row.new_exceed_ratio}
            level={row.new_level}
            levelLabel={row.new_level_label}
          />
        </span>
      )
    },
    {
      key: 'prev_annotation',
      title: '被重置的原标注',
      render: (row) =>
        row.prev_annotation_status && row.prev_annotation_status !== 'pending' ? (
          <div className="small">
            <Tag tone="warning">{row.prev_annotation_status_label}</Tag>{' '}
            {row.prev_annotator || '未署名'}
          </div>
        ) : (
          <span className="muted small">无</span>
        )
    },
    {
      key: 'operator',
      title: '操作人 / 原因',
      render: (row) => (
        <div style={{ maxWidth: 240 }}>
          <div className="small strong">{row.operator}</div>
          <div className="small muted">{row.reason}</div>
        </div>
      )
    }
  ]

  return (
    <div className="stack">
      {query.error ? <Alert tone="error">{query.error.message}</Alert> : null}
      <DataTable
        columns={columns}
        rows={query.items}
        loading={query.loading}
        emptyText="当前筛选条件下还没有覆盖版本记录"
        emptyIcon="🕘"
      />
      <Pagination
        page={query.page}
        pages={query.pages}
        total={query.total}
        pageSize={query.pageSize}
        onPageChange={query.setPage}
        onPageSizeChange={query.setPageSize}
      />
    </div>
  )
}
