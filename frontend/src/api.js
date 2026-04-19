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
