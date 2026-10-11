import { useState } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { login } from '../api';
import { safeNext, withNext } from '../lib/safeNext';
import './auth.css';

function LoginPage() {
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
            await login(username, password);
            navigate(next || '/dashboard/');
        } catch {
            setError('Неверный логин или пароль');
        }
    }

    return (
        <div className="page page--form">
            <div className="card auth-card">
                <h1 className="auth-card__title">Вход</h1>
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
                            autoComplete="current-password"
                            value={password}
                            onChange={e => setPassword(e.target.value)}
                        />
                    </div>
                    <button type="submit" className="btn btn-primary btn-block">
                        Войти
                    </button>
                </form>
                <p className="auth-card__footer">
                    Нет аккаунта? <Link to={withNext('/register/', next)}>Зарегистрироваться</Link>
                </p>
            </div>
        </div>
    );
}

export default LoginPage;