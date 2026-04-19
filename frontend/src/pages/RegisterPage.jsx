import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import api from '../api';

function RegisterPage() {
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [role, setRole] = useState('STUDENT');
    const [error, setError] = useState('');
    const navigate = useNavigate();

    async function handleSubmit(e) {
        e.preventDefault();
        setError('');
        try {
            await api.post('/auth/register/', { username, password, role });
            navigate('/login/');
        } catch (err) {
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
                <div style={{ marginBottom: '15px' }}>
                    <select
                        value={role}
                        onChange={e => setRole(e.target.value)}
                        style={{ width: '100%', padding: '8px' }}
                    >
                        <option value="STUDENT">Учащийся</option>
                        <option value="AUTHOR">Автор</option>
                    </select>
                </div>
                <button type="submit" style={{ width: '100%', padding: '10px' }}>
                    Зарегистрироваться
                </button>
            </form>
            <p style={{ marginTop: '15px', textAlign: 'center' }}>
                Уже есть аккаунт? <Link to="/login/">Войти</Link>
            </p>
        </div>
    );
}

export default RegisterPage;