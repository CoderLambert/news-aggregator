import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 10000,
})

export const fetchNews = (params = {}) =>
  api.get('/news/', { params }).then(res => res.data)

export const fetchSemanticSearch = (query, params = {}) =>
  api.get('/news/', { params: { ...params, search: query, mode: 'semantic' } }).then(res => res.data)

export const fetchNewsDetail = (id) =>
  api.get(`/news/${id}/`).then(res => res.data)

export const fetchCategories = () =>
  api.get('/categories/').then(res => res.data)

export const fetchSources = () =>
  api.get('/sources/').then(res => res.data)
