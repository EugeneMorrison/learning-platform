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

// Get a new access token with the stored refresh token (one request at a time,
// shared by every caller). Resolves to the new token; rejects when there is no
// refresh token or the server refuses it (err.response.status 401: log in again).
export function refreshAccessToken() {
    const refreshToken = localStorage.getItem('refresh_token');
    if (!refreshToken) return Promise.reject(new Error('No refresh token'));
    if (!refreshInFlight) {
        refreshInFlight = axios
            .post(`${AUTH_BASE}/token/refresh/`, { refresh: refreshToken })
            .then((res) => {
                const newAccess = res.data.access;
                localStorage.setItem('access_token', newAccess);
                currentToken = newAccess;
                return newAccess;
            })
            .finally(() => { refreshInFlight = null; });
    }
    return refreshInFlight;
}

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

        if (localStorage.getItem('refresh_token')) {
            try {
                const newAccess = await refreshAccessToken();
                originalRequest.headers.Authorization = `Bearer ${newAccess}`;
                return api(originalRequest);
            } catch {
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

// Save a token pair from /auth/login/ and use it right away.
export const storeTokens = ({ access, refresh }) => {
    localStorage.setItem('access_token', access);
    localStorage.setItem('refresh_token', refresh);
    currentToken = access; // Immediately available for the next request
};

export const login = async (username, password) => {
    const response = await axios.post(`${AUTH_BASE}/login/`, { username, password });
    storeTokens(response.data.tokens);
    return response;
};

// Sign up. The server emails a confirmation link and returns { detail, email };
// no tokens: the account can log in once the address is confirmed. `next` (a
// local path) is carried through the link back to the login page. No role in
// the body: public registration always creates a student.
// The two acceptances are separate (personal data consent; user agreement and privacy policy).
export const register = async ({ username, email, password, acceptConsent, acceptTerms, next }) => {
    const response = await axios.post(`${AUTH_BASE}/register/`, {
        username, email, password, accept_consent: acceptConsent, accept_terms: acceptTerms, next,
    });
    return response.data;
};

// Ask for a new confirmation link (the answer is the same whether or not the
// address is registered). 429 after 3 requests an hour.
export const resendConfirmation = async (email, next) => {
    const response = await axios.post(`${AUTH_BASE}/resend-confirmation/`, { email, next });
    return response.data;
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
