import { useEffect, useMemo, useState } from 'react'
import Modal from '../../../components/common/Modal.jsx'
import { Field, Input, Textarea } from '../../../components/common/FormField.jsx'
import { Alert } from '../../../components/common/Feedback.jsx'
import Tag from '../../../components/common/Tag.jsx'
import {
  EXCEEDANCE_LEVEL_LABELS,
  EXCEEDANCE_LEVEL_TONE,
  EXCEEDANCE_STATUS_TONE
} from '../../../constants/index.js'
import { formatDateTime, formatNumber, formatRatio } from '../../../utils/format.js'

const CHANGE_META = {
  unchanged: { tone: 'neutral', label: '结论不变' },
  exceeded_to_normal: { tone: 'success', label: '超标撤销' },
  normal_to_exceeded: { tone: 'danger', label: '新增超标' },
  level_changed: { tone: 'warning', label: '超标程度变化' }
}

function ConclusionCell({ conclusion, status, statusLabel }) {
  if (!conclusion?.is_exceeded) {
    return conclusion?.applicable === false ? <Tag tone="neutral">仅记录</Tag> : <Tag tone="success">达标</Tag>
  }
  return (
    <div className="stack" style={{ gap: 2 }}>
      <Tag tone="danger">超标 {formatRatio(conclusion.ratio)}</Tag>
      <Tag tone={EXCEEDANCE_LEVEL_TONE[conclusion.level]}>
        {EXCEEDANCE_LEVEL_LABELS[conclusion.level]}
      </Tag>
      {status ? <Tag tone={EXCEEDANCE_STATUS_TONE[status]}>{statusLabel || status}</Tag> : null}
    </div>
  )
}

export default function OverwriteDialog({ data, busy, onClose, onConfirm }) {
  const duplicates = data?.duplicates ?? []
  const [selected, setSelected] = useState({})
  const [operator, setOperator] = useState('')
  const [reason, setReason] = useState('')
  const [errors, setErrors] = useState({})

  useEffect(() => {
    if (!data) return
    const next = {}
    data.duplicates.forEach((item) => {
      next[item.pollutant] = true
    })
    setSelected(next)
    setOperator('')
    setReason('')
    setErrors({})
  }, [data])

  const chosen = useMemo(
    () => duplicates.filter((item) => selected[item.pollutant]),
    [duplicates, selected]
  )
  const annotatedChosen = chosen.filter((item) => item.annotation_will_reset)
  const revokeChosen = chosen.filter((item) => item.exceedance_will_revoke)

  const toggle = (pollutant) => {
    setSelected((prev) => ({ ...prev, [pollutant]: !prev[pollutant] }))
  }

  const submit = () => {
    const next = {}
    if (!operator.trim()) next.operator = '覆盖必须填写操作人'
    if (!reason.trim()) next.reason = '覆盖必须填写原因, 便于审计追溯'
    if (chosen.length === 0) next.selection = '请至少选择一项覆盖, 或点击"全部跳过"'
    setErrors(next)
    if (Object.keys(next).length) return

    onConfirm({
      operator: operator.trim(),
      reason: reason.trim(),
      overwrite_pollutants: chosen.map((item) => item.pollutant),
      entries: chosen.map((item) => ({
        pollutant: item.pollutant,
        value: item.new_value,
        overwrite: true,
        base_version: item.version
      }))
    })
  }

  return (
    <Modal
      open={Boolean(data)}
      wide
      title="同一时刻已存在数据"
      onClose={busy ? undefined : onClose}
      closeOnOverlay={false}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            全部跳过 ({duplicates.length})
          </button>
          <button type="button" className="btn btn-primary" onClick={submit} disabled={busy}>
            {busy ? '覆盖提交中...' : `覆盖选中项 (${chosen.length})`}
          </button>
        </>
      }
    >
      <div className="stack">
        <Alert tone="warning">
          以下因子在 {formatDateTime(data?.measured_at)} 已存在数据。勾选需要覆盖的因子并填写覆盖原因;
          未勾选的因子将跳过、保留原值。
        </Alert>

        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th style={{ width: 40 }}>覆盖</th>
                <th>因子</th>
                <th>原数值</th>
                <th>新数值</th>
                <th>差异</th>
                <th>原结论 / 标注</th>
                <th>重判结论</th>
                <th>变化</th>
              </tr>
            </thead>
            <tbody>
              {duplicates.map((item) => {
                const checked = selected[item.pollutant]
                const change = CHANGE_META[item.conclusion_change] || CHANGE_META.unchanged
                return (
                  <tr key={item.pollutant} className={checked ? '' : 'muted-row'}>
                    <td>
                      <input
                        type="checkbox"
                        checked={Boolean(checked)}
                        onChange={() => toggle(item.pollutant)}
                      />
                    </td>
                    <td className="cell-nowrap">{item.pollutant_label}</td>
                    <td className="cell-nowrap">
                      <span className="strong">{formatNumber(item.existing_value)}</span>
                      <span className="muted small"> {item.unit}</span>
                      <div className="small muted">v{item.version}</div>
                    </td>
                    <td className="cell-nowrap">
                      <span className={item.delta > 0 ? 'danger-text strong' : 'success-text strong'}>
                        {formatNumber(item.new_value)}
                      </span>
                      <span className="muted small"> {item.unit}</span>
                    </td>
                    <td className="cell-nowrap">
                      <div className={item.delta > 0 ? 'danger-text' : 'success-text'}>
                        {item.delta > 0 ? '+' : ''}
                        {formatNumber(item.delta)}
                      </div>
                      {item.delta_percent !== null ? (
                        <div className="small muted">
                          {item.delta_percent > 0 ? '+' : ''}
                          {item.delta_percent}%
                        </div>
                      ) : null}
                    </td>
                    <td>
                      <ConclusionCell
                        conclusion={{
                          is_exceeded: item.existing.is_exceeded,
                          ratio: item.existing.ratio,
                          level: item.existing.level,
                          applicable: item.existing.limit_value !== null
                        }}
                        status={item.existing.status}
                        statusLabel={item.existing.status_label}
                      />
                    </td>
                    <td>
                      <ConclusionCell
                        conclusion={item.incoming}
                        status={null}
                      />
                    </td>
                    <td className="cell-nowrap">
                      <Tag tone={change.tone}>{change.label}</Tag>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {annotatedChosen.length ? (
          <Alert tone="error">
            {annotatedChosen
              .map((item) => `${item.pollutant_label}(${item.existing.status_label})`)
              .join('、')}
            {' '}已有确认/忽略标注, 覆盖后超标结论将按新值重新判定, 原标注作废并转为待标注, 该次覆盖会被记录。
          </Alert>
        ) : null}
        {revokeChosen.length ? (
          <Alert tone="info">
            {revokeChosen.map((item) => item.pollutant_label).join('、')} 覆盖后将不再超标, 对应超标记录会被撤销并在版本中留痕。
          </Alert>
        ) : null}

        <div className="form-grid">
          <Field label="覆盖操作人" required error={errors.operator}>
            <Input
              value={operator}
              onChange={(event) => setOperator(event.target.value)}
              placeholder="如: 王敏"
              invalid={Boolean(errors.operator)}
            />
          </Field>
          <Field
            label="覆盖原因"
            required
            error={errors.reason}
            hint="将记录到版本历史, 与每次结论变更绑定"
          >
            <Textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="如: 在线设备人工比对, 原值为仪器校准期异常数据"
              invalid={Boolean(errors.reason)}
            />
          </Field>
        </div>
        {errors.selection ? <Alert tone="error">{errors.selection}</Alert> : null}
      </div>
    </Modal>
  )
}
