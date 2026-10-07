import { useState } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import api, { storeTokens } from '../api';
import { safeNext, withNext } from '../lib/safeNext';

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
        <div style={{ maxWidth: '400px', margin: '100px auto', padding: '20px' }}>
            <h2>Регистрация</h2>
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
                    Зарегистрироваться
                </button>
            </form>
            <p style={{ marginTop: '15px', textAlign: 'center' }}>
                Уже есть аккаунт? <Link to={withNext('/login/', next)}>Войти</Link>
            </p>
        </div>
    );
}

export default RegisterPage;