import { useState } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import api, { storeTokens } from '../api';
import { safeNext, withNext } from '../lib/safeNext';
import './auth.css';

function RegisterPage() {
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const next = safeNext(searchParams.get('next'));

    async function handleSubmit(e) {
        e.preventDefault();
        setError('');
        try {
            // No role: public registration always creates a student (set by the server).
            const response = await api.post('/auth/register/', { username, password });
            if (next) {
                // Register returns tokens: sign in right away so the user lands on
                // `next` (e.g. /enroll/<id>/) instead of a second login form.
                storeTokens(response.data.tokens);
                navigate(next);
            } else {
                navigate('/login/');
            }
        } catch {
            setError('Ошибка регистрации. Попробуйте другое имя пользователя.');
        }
    }

    return (
        <div className="page page--form">
            <div className="card auth-card">
                <h1 className="auth-card__title">Регистрация</h1>
                {error && <p className="notice notice-danger auth-card__error" role="alert">{error}</p>}
                <form onSubmit={handleSubmit}>
                    <div className="field">
                        <input
                            className="input"
                            type="text"
                            placeholder="Имя пользователя"
                            aria-label="Имя пользователя"
                            autoComplete="username"
                            value={username}
                            onChange={e => setUsername(e.target.value)}
                        />
                    </div>
                    <div className="field">
                        <input
                            className="input"
                            type="password"
                            placeholder="Пароль"
                            aria-label="Пароль"
                            autoComplete="new-password"
                            value={password}
                            onChange={e => setPassword(e.target.value)}
                        />
                    </div>
                    <button type="submit" className="btn btn-primary btn-block">
                        Зарегистрироваться
                    </button>
                </form>
                <p className="auth-card__footer">
                    Уже есть аккаунт? <Link to={withNext('/login/', next)}>Войти</Link>
                </p>
            </div>
        </div>
    );
}

export default RegisterPage;