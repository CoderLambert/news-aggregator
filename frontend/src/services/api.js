import axios from 'axios'
import { LANG_KEY } from '../context/LanguageContext'

const api = axios.create({
  baseURL: '/api',
  timeout: 10000,
})

// Interceptor to add lang parameter to all requests
api.interceptors.request.use((config) => {
  const lang = localStorage.getItem(LANG_KEY) || 'zh'
  if (lang && lang !== 'original') {
    config.params = config.params || {}
    config.params.lang = lang
  }
  return config
})

export const fetchNews = (params = {}) =>
  api.get('/news/', { params }).then(res => res.data)

export const fetchSemanticSearch = (query, params = {}) =>
  api.get('/news/', { params: { ...params, search: query, mode: 'semantic' } }).then(res => res.data)

export const fetchNewsDetail = (id) =>
  api.get(`/news/${id}/`).then(res => res.data)

export const fetchFullArticle = (id) =>
  api.post(`/news/${id}/fetch-full/`).then(res => res.data)

export const fetchCategories = () =>
  api.get('/categories/').then(res => res.data)

export const fetchSources = () =>
  api.get('/sources/').then(res => res.data)
