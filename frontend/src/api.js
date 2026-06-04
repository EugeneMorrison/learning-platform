import axios from 'axios';

// In dev mode (npm run dev) — call Django on port 8000 directly
// In production (built, served by Django) — use relative URL (same origin)
const API_BASE = import.meta.env.DEV
    ? 'http://127.0.0.1:8000/api'
    : '/api';

// Create axios instance with default settings
const api = axios.create({
    baseURL: API_BASE,
});

// Module-level token — updated immediately by login(), read by interceptor.
// Initialized from localStorage so page refreshes pick up the saved token.
let currentToken = localStorage.getItem('access_token');

// Automatically attach JWT token to every request
api.interceptors.request.use((config) => {
    if (currentToken) {
        config.headers.Authorization = `Bearer ${currentToken}`;
    }
    return config;
});

// Self-heal on 401: try to refresh the access token using the stored refresh
// token, then retry the original request with the new token. Only if refresh
// itself fails do we clear tokens and retry unauthenticated (so public endpoints
// like lessons/blocks still resolve, while protected ones bubble up a 401 for
// the UI to handle).
let refreshInFlight = null;

api.interceptors.response.use(
    (response) => response,
    async (error) => {
        const originalRequest = error.config;
        if (
            error.response?.status !== 401 ||
            !currentToken ||
            originalRequest._retriedAfter401
        ) {
            return Promise.reject(error);
        }
        originalRequest._retriedAfter401 = true;

        const refreshToken = localStorage.getItem('refresh_token');
        if (refreshToken) {
            try {
                if (!refreshInFlight) {
                    refreshInFlight = axios
                        .post(`${AUTH_BASE}/token/refresh/`, { refresh: refreshToken })
                        .finally(() => { refreshInFlight = null; });
                }
                const res = await refreshInFlight;
                const newAccess = res.data.access;
                localStorage.setItem('access_token', newAccess);
                currentToken = newAccess;
                originalRequest.headers.Authorization = `Bearer ${newAccess}`;
                return api(originalRequest);
            } catch (refreshErr) {
                // refresh token also expired/invalid — fall through to clear+retry
            }
        }

        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        currentToken = null;
        delete originalRequest.headers.Authorization;
        return api(originalRequest);
    }
);

// AUTH — uses plain axios (not intercepted instance) to avoid expired token bug
const AUTH_BASE = import.meta.env.DEV
    ? 'http://127.0.0.1:8000/api/auth'
    : '/api/auth';

export const login = async (username, password) => {
    const response = await axios.post(`${AUTH_BASE}/login/`, { username, password });
    const { access, refresh } = response.data.tokens;
    localStorage.setItem('access_token', access);
    localStorage.setItem('refresh_token', refresh);
    currentToken = access; // Immediately available for the next request
    return response;
};

export const logout = () => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    currentToken = null;
};

// COURSES
export const getCourses = () =>
    api.get('/courses/');

// LESSONS
export const getLesson = (lessonId) =>
    api.get(`/lessons/${lessonId}/`);

// BLOCKS - get all blocks for a lesson
export const getBlocks = (lessonId) =>
    api.get(`/blocks/?lesson=${lessonId}`);

export default api;
