import { useState } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { login } from '../api';
import { safeNext, withNext } from '../lib/safeNext';

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
        } catch (err) {
            setError('Неверный логин или пароль');
        }
    }

    return (
        <div style={{ maxWidth: '400px', margin: '100px auto', padding: '20px' }}>
            <h2>Вход</h2>
            {error && <p style={{ color: 'red' }}>{error}</p>}
            <form onSubmit={handleSubmit}>
                <div style={{ marginBottom: '15px' }}>
                    <input
                        type="text"
                        placeholder="Имя пользователя"
                        value={username}
                        onChange={e => setUsername(e.target.value)}
                        style={{ width: '100%', padding: '8px' }}
                    />
                </div>
                <div style={{ marginBottom: '15px' }}>
                    <input
                        type="password"
                        placeholder="Пароль"
                        value={password}
                        onChange={e => setPassword(e.target.value)}
                        style={{ width: '100%', padding: '8px' }}
                    />
                </div>
                <button type="submit" style={{ width: '100%', padding: '10px' }}>
                    Войти
                </button>
            </form>
            <p style={{ marginTop: '15px', textAlign: 'center' }}>
                Нет аккаунта? <Link to={withNext('/register/', next)}>Зарегистрироваться</Link>
            </p>
        </div>
    );
}

export default LoginPage;