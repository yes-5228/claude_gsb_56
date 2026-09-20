import { useMemo, useState } from 'react'
import { createEntries } from '../../../api/measurements.js'
import Modal from '../../../components/common/Modal.jsx'
import Tag from '../../../components/common/Tag.jsx'
import { Alert } from '../../../components/common/Feedback.jsx'
import { Field, Input, Textarea } from '../../../components/common/FormField.jsx'
import { useToast } from '../../../components/common/ToastProvider.jsx'
import { EXCEEDANCE_LEVEL_LABELS, EXCEEDANCE_STATUS_LABELS } from '../../../constants/index.js'
import { formatDateTime, formatNumber } from '../../../utils/format.js'

function JudgeTag({ exceeded, ratio, level }) {
  if (exceeded) {
    const levelLabel = EXCEEDANCE_LEVEL_LABELS[level] || ''
    return (
      <Tag tone="danger">
        超标 {formatNumber(ratio, 2)} 倍{levelLabel ? ` · ${levelLabel}` : ''}
      </Tag>
    )
  }
  return <Tag tone="success">达标</Tag>
}

function DiffValue({ diff, unit }) {
  if (diff === null || diff === undefined) return <span className="muted">-</span>
  if (Math.abs(diff) < 1e-9) return <span className="muted">±0 {unit || ''}</span>
  const tone = diff > 0 ? 'danger-text' : 'success-text'
  return (
    <span className={`${tone} strong`}>
      {diff > 0 ? '+' : ''}
      {formatNumber(diff)} {unit || ''}
    </span>
  )
}

/**
 * 重复数据差异对比弹窗: 同一时刻同一因子已有数据时,
 * 逐因子展示新旧数值与判定差异, 由录入人选择跳过或覆盖;
 * 覆盖必须填写操作人与原因, 并携带期望版本号防止并发互相覆盖。
 */
export default function OverwriteDialog({ conflict, onClose, onSubmitted }) {
  const toast = useToast()
  const [rows, setRows] = useState(conflict?.duplicates ?? [])
  const [decisions, setDecisions] = useState({})
  const [operator, setOperator] = useState(conflict?.context?.recorder || '')
  const [reason, setReason] = useState('')
  const [errors, setErrors] = useState({})
  const [notice, setNotice] = useState(null)
  const [busy, setBusy] = useState(false)

  const context = conflict?.context ?? {}

  const chosen = useMemo(
    () => rows.filter((row) => decisions[row.pollutant] === 'overwrite'),
    [rows, decisions]
  )

  const decide = (pollutant, decision) => {
    setDecisions((prev) => ({ ...prev, [pollutant]: decision }))
  }

  const refreshDiff = async () => {
    // 重新拉取最新差异 (不改变任何数据): 全部重复时后端返回 409 + 差异载荷
    try {
      await createEntries({
        station_id: context.station_id,
        measured_at: context.measured_at,
        period: context.period,
        data_source: context.data_source,
        recorder: operator || null,
        remark: context.remark || null,
        overwrite: false,
        entries: rows.map((row) => ({ pollutant: row.pollutant, value: row.value }))
      })
    } catch (error) {
      if (error.payload?.duplicates?.length) {
        setRows(error.payload.duplicates)
        setDecisions({})
      }
    }
  }

  const submit = async () => {
    if (chosen.length === 0) {
      onClose?.()
      return
    }
    const nextErrors = {}
    if (!operator.trim()) nextErrors.operator = '覆盖已有数据时必须填写操作人'
    if (!reason.trim()) nextErrors.reason = '覆盖已有数据时必须填写覆盖原因'
    setErrors(nextErrors)
    if (Object.keys(nextErrors).length) return

    setBusy(true)
    setNotice(null)
    try {
      const result = await createEntries({
        station_id: context.station_id,
        measured_at: context.measured_at,
        period: context.period,
        data_source: context.data_source,
        recorder: operator.trim(),
        remark: context.remark || null,
        overwrite: true,
        overwrite_reason: reason.trim(),
        entries: chosen.map((row) => ({
          pollutant: row.pollutant,
          value: row.value,
          expected_version: row.existing_version
        }))
      })
      const resetCount = (result.revisions || []).filter(
        (item) => item.prev_annotation_status && item.prev_annotation_status !== 'pending'
      ).length
      toast.success(
        `已覆盖 ${result.summary.updated_count} 条数据并重新判定超标${
          resetCount ? `, ${resetCount} 条原标注已重置待复核` : ''
        }`
      )
      onSubmitted?.(result)
      onClose?.()
    } catch (error) {
      if (error.code === 'VERSION_CONFLICT') {
        setNotice(error.message)
        toast.error('覆盖未生效: 数据刚被他人更新')
        await refreshDiff()
      } else {
        setErrors(error.fields || {})
        setNotice(error.message)
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={Boolean(conflict)}
      wide
      title="重复数据差异对比"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            全部跳过
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={submit}
            disabled={busy || chosen.length === 0}
          >
            {busy ? '提交中...' : `覆盖所选 (${chosen.length})`}
          </button>
        </>
      }
    >
      <div className="stack">
        <Alert tone="warning">
          以下因子在该时刻已有数据。请核对新旧数值差异, 逐条选择“跳过”或“覆盖”;
          覆盖会按新数值重新判定超标, 已确认/已忽略的标注将被重置并留痕。
        </Alert>
        {notice ? <Alert tone="error">{notice}</Alert> : null}

        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>监测因子</th>
                <th className="text-right">原数值</th>
                <th className="text-right">新数值</th>
                <th className="text-right">差异</th>
                <th>判定变化</th>
                <th>处理方式</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const decision = decisions[row.pollutant] || 'skip'
                return (
                  <tr key={row.pollutant}>
                    <td>
                      <div>{row.pollutant_label}</div>
                      <div className="small muted">
                        原记录: {row.existing_recorder || '未署名'} ·{' '}
                        {formatDateTime(row.existing_updated_at)}
                        {row.existing_annotation_status &&
                        row.existing_annotation_status !== 'pending' ? (
                          <span className="danger-text">
                            {' '}
                            · 原标注「
                            {EXCEEDANCE_STATUS_LABELS[row.existing_annotation_status] ||
                              row.existing_annotation_status}
                            」将被重置
                          </span>
                        ) : null}
                      </div>
                    </td>
                    <td className="text-right cell-nowrap">
                      {formatNumber(row.existing_value)} {row.unit || ''}
                    </td>
                    <td className="text-right cell-nowrap strong">
                      {formatNumber(row.value)} {row.unit || ''}
                    </td>
                    <td className="text-right cell-nowrap">
                      <DiffValue diff={row.value_diff} unit={row.unit} />
                    </td>
                    <td className="cell-nowrap">
                      <JudgeTag
                        exceeded={row.existing_is_exceeded}
                        ratio={row.existing_exceed_ratio}
                        level={row.existing_level}
                      />
                      <span className="muted"> → </span>
                      <JudgeTag
                        exceeded={row.new_is_exceeded}
                        ratio={row.new_exceed_ratio}
                        level={row.new_level}
                      />
                    </td>
                    <td>
                      <div className="inline" style={{ flexWrap: 'nowrap', gap: 12 }}>
                        <label className="checkbox">
                          <input
                            type="radio"
                            name={`decision-${row.pollutant}`}
                            checked={decision === 'skip'}
                            onChange={() => decide(row.pollutant, 'skip')}
                          />
                          <span>跳过</span>
                        </label>
                        <label className="checkbox">
                          <input
                            type="radio"
                            name={`decision-${row.pollutant}`}
                            checked={decision === 'overwrite'}
                            onChange={() => decide(row.pollutant, 'overwrite')}
                          />
                          <span>覆盖</span>
                        </label>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        <div className="form-grid">
          <Field label="操作人" required error={errors.operator || errors.recorder}>
            <Input
              value={operator}
              onChange={(event) => setOperator(event.target.value)}
              invalid={Boolean(errors.operator || errors.recorder)}
              placeholder="覆盖操作将记录该操作人"
            />
          </Field>
          <Field
            label="覆盖原因"
            required
            error={errors.reason || errors.overwrite_reason}
            hint="覆盖会留下版本记录, 原因将随版本保存并可回看"
          >
            <Textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              invalid={Boolean(errors.reason || errors.overwrite_reason)}
              placeholder="如: 设备校准后复测, 原数据为校准前异常值"
            />
          </Field>
        </div>
      </div>
    </Modal>
  )
}
