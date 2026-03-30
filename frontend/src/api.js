import axios from 'axios';

// Base URL of your Django backend
const API_BASE = 'http://127.0.0.1:8000/api';

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

// AUTH
export const login = (username, password) =>
    axios.post('http://127.0.0.1:8000/api/auth/login/', { username, password });

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