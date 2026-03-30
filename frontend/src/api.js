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

// Automatically attach JWT token to every request if it exists
api.interceptors.request.use((config) => {
    const token = localStorage.getItem('access_token');
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

// AUTH — uses plain axios (not intercepted instance) to avoid expired token bug
const AUTH_BASE = import.meta.env.DEV
    ? 'http://127.0.0.1:8000/api/auth'
    : '/api/auth';

export const login = (username, password) =>
    axios.post(`${AUTH_BASE}/login/`, { username, password });

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