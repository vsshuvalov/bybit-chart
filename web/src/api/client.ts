/**
 * Centralized API client configuration.
 *
 * Uses relative URLs to avoid mixed content issues under HTTPS.
 * Base URL can be overridden via VITE_API_BASE_URL env var.
 */

import axios from 'axios'

export const apiClient = axios.create({
  baseURL: '/api/v1',
  timeout: 10_000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Add response interceptor for error logging
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response) {
      console.error('[API Error]', error.response.status, error.response.data)
    } else if (error.request) {
      console.error('[API Error] No response received:', error.message)
    } else {
      console.error('[API Error]', error.message)
    }
    return Promise.reject(error)
  }
)
