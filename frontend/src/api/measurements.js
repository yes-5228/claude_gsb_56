import http, { toParams } from './client.js'

export const listMeasurements = (params) => http.get('/measurements', { params: toParams(params) })
export const previewEntries = (payload) => http.post('/measurements/preview', payload)
export const createEntries = (payload) => http.post('/measurements/entries', payload)
export const deleteMeasurement = (id) => http.delete(`/measurements/${id}`)
export const entryContext = () => http.get('/measurements/entry-context')
export const listRevisions = (params) =>
  http.get('/measurements/revisions', { params: toParams(params) })
export const listMeasurementRevisions = (id) => http.get(`/measurements/${id}/revisions`)
export const exportMeasurementsUrl = (params) =>
  `/measurements/export?${new URLSearchParams(toParams(params)).toString()}`
