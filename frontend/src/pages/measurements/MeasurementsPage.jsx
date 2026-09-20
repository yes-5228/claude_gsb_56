import { useCallback, useState } from 'react'
import { downloadFile } from '../../api/client.js'
import {
  deleteMeasurement,
  exportMeasurementsUrl,
  listMeasurements
} from '../../api/measurements.js'
import ConfirmDialog from '../../components/common/ConfirmDialog.jsx'
import Pagination from '../../components/common/Pagination.jsx'
import { SectionCard } from '../../components/common/Card.jsx'
import { Alert } from '../../components/common/Feedback.jsx'
import { useToast } from '../../components/common/ToastProvider.jsx'
import { useListQuery } from '../../hooks/useListQuery.js'
import { saveBlob } from '../../utils/download.js'
import EntryForm from './components/EntryForm.jsx'
import EntryResultPanel from './components/EntryResultPanel.jsx'
import MeasurementFilters from './components/MeasurementFilters.jsx'
import MeasurementTable from './components/MeasurementTable.jsx'
import RevisionHistoryModal from './components/RevisionHistoryModal.jsx'
import RevisionListPanel from './components/RevisionListPanel.jsx'

const INITIAL_FILTERS = {
  station_id: '',
  pollutant: '',
  period: '',
  is_exceeded: '',
  date_from: '',
  date_to: ''
}

export default function MeasurementsPage() {
  const toast = useToast()
  const query = useListQuery(listMeasurements, INITIAL_FILTERS)
  const [result, setResult] = useState(null)
  const [pendingDelete, setPendingDelete] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [revisionTarget, setRevisionTarget] = useState(null)
  const [listTab, setListTab] = useState('data')

  const handleSubmitted = useCallback(
    (payload) => {
      setResult({ kind: 'submit', payload })
      query.reload()
    },
    [query]
  )

  const handleDelete = useCallback(async () => {
    if (!pendingDelete) return
    setDeleting(true)
    try {
      await deleteMeasurement(pendingDelete.id)
      toast.success('监测数据已删除')
      setPendingDelete(null)
      query.reload()
    } catch (error) {
      toast.error(error.message)
    } finally {
      setDeleting(false)
    }
  }, [pendingDelete, query, toast])

  const handleExport = useCallback(async () => {
    setExporting(true)
    try {
      const blob = await downloadFile(exportMeasurementsUrl(query.filters))
      saveBlob(blob, `监测数据_${Date.now()}.csv`)
      toast.success('导出任务已完成, 请查看下载文件')
    } catch (error) {
      toast.error(error.message)
    } finally {
      setExporting(false)
    }
  }, [query.filters, toast])

  return (
    <>
      <div className="grid-2">
        <EntryForm
          onPreview={(payload) => setResult({ kind: 'preview', payload })}
          onSubmitted={handleSubmitted}
        />
        <EntryResultPanel result={result} summary={query.summary} onClose={() => setResult(null)} />
      </div>

      <MeasurementFilters
        value={query.filters}
        loading={query.loading}
        onSubmit={(next) => query.setFilters(next)}
        onReset={() => query.setFilters(INITIAL_FILTERS)}
      />

      {query.error ? <Alert tone="error">{query.error.message}</Alert> : null}

      <SectionCard
        title={listTab === 'data' ? '最近录入的数据' : '覆盖版本历史'}
        hint={
          listTab === 'data'
            ? '按监测时间倒序展示, 便于核对刚提交的记录'
            : '每次覆盖留下的版本快照, 按覆盖时间倒序回看'
        }
        actions={
          <>
            <div className="inline" style={{ flexWrap: 'nowrap' }}>
              <button
                type="button"
                className={`btn btn-sm ${listTab === 'data' ? 'btn-primary' : ''}`}
                onClick={() => setListTab('data')}
              >
                数据列表
              </button>
              <button
                type="button"
                className={`btn btn-sm ${listTab === 'revisions' ? 'btn-primary' : ''}`}
                onClick={() => setListTab('revisions')}
              >
                覆盖历史
              </button>
            </div>
            {listTab === 'data' ? (
              <>
                <button type="button" className="btn btn-sm" onClick={query.reload} disabled={query.loading}>
                  刷新
                </button>
                <button type="button" className="btn btn-sm btn-primary" onClick={handleExport} disabled={exporting}>
                  {exporting ? '导出中...' : '导出 CSV'}
                </button>
              </>
            ) : null}
          </>
        }
      >
        {listTab === 'data' ? (
          <>
            <MeasurementTable
              rows={query.items}
              loading={query.loading}
              onDelete={(row) => setPendingDelete(row)}
              onShowRevisions={(row) => setRevisionTarget(row)}
            />
            <Pagination
              page={query.page}
              pages={query.pages}
              total={query.total}
              pageSize={query.pageSize}
              onPageChange={query.setPage}
              onPageSizeChange={query.setPageSize}
            />
          </>
        ) : (
          <RevisionListPanel filters={query.filters} />
        )}
      </SectionCard>

      <RevisionHistoryModal
        measurement={revisionTarget}
        onClose={() => setRevisionTarget(null)}
      />

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        danger
        busy={deleting}
        title="删除监测数据"
        message={`确认删除 ${pendingDelete?.pollutant_label || ''} 的这条记录吗?`}
        detail="若该记录已产生超标记录, 对应的标注信息也会一并删除。"
        confirmText="确认删除"
        onConfirm={handleDelete}
        onCancel={() => setPendingDelete(null)}
      />
    </>
  )
}
