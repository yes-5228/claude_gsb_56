import http, { toParams } from './client.js'

export const listMeasurements = (params) => http.get('/measurements', { params: toParams(params) })
export const previewEntries = (payload) => http.post('/measurements/preview', payload)
export const checkConflicts = (payload) => http.post('/measurements/conflicts', payload)
export const createEntries = (payload) => http.post('/measurements/entries', payload)
export const deleteMeasurement = (id) => http.delete(`/measurements/${id}`)
export const listMeasurementVersions = (id) => http.get(`/measurements/${id}/versions`)
export const listConclusionChanges = (params) =>
  http.get('/measurements/conclusion-changes', { params: toParams(params) })
export const entryContext = () => http.get('/measurements/entry-context')
export const exportMeasurementsUrl = (params) =>
  `/measurements/export?${new URLSearchParams(toParams(params)).toString()}`
