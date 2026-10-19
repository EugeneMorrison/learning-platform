import { useState } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { register } from '../api';
import { goToNext, safeNext, withNext } from '../lib/safeNext';
import './auth.css';

// "не меньше N символа/символов": genitive singular after 1, 21, 31… (not 11).
function symbolsWord(n) {
    return n % 10 === 1 && n % 100 !== 11 ? 'символа' : 'символов';
}

// Russian wording for the password validator codes the server sends back
// (Django's AUTH_PASSWORD_VALIDATORS). The minimum length comes from the server
// (min_length), so it follows the configured MinimumLengthValidator.
const PASSWORD_PROBLEMS = {
    password_too_short: data => (data.min_length
        ? `нужно не меньше ${data.min_length} ${symbolsWord(data.min_length)}`
        : null),
    password_too_common: () => 'это один из самых распространённых паролей',
    password_entirely_numeric: () => 'пароль не может состоять только из цифр',
    password_too_similar: () => 'пароль слишком похож на имя пользователя',
};

// Server error (see register_view in api/auth_views.py) → { message, field }.
// `field` marks the input to highlight: 'username', 'password' or null.
function describeError(err) {
    const data = err.response?.data;
    if (!err.response) {
        return { message: 'Нет связи с сервером. Проверьте подключение и попробуйте ещё раз.', field: null };
    }
    switch (data?.code) {
        case 'required':
            return { message: 'Введите имя пользователя и пароль.', field: data.fields?.[0] || null };
        case 'invalid_username':
            return {
                message: 'Имя пользователя может содержать только буквы, цифры и символы @ . + - _ (без пробелов).',
                field: 'username',
            };
        case 'username_taken':
            return { message: 'Это имя пользователя уже занято. Выберите другое.', field: 'username' };
        case 'weak_password': {
            // Unknown code (or no min_length): fall back to the server's own message.
            const problems = (data.codes || []).map((code, i) => PASSWORD_PROBLEMS[code]?.(data) || data.messages?.[i]);
            return { message: `Пароль слишком простой: ${problems.join('; ')}.`, field: 'password' };
        }
        default:
            return { message: 'Не удалось зарегистрироваться. Попробуйте ещё раз.', field: null };
    }
}

function RegisterPage() {
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState(null); // { message, field }
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const next = safeNext(searchParams.get('next'));

    async function handleSubmit(e) {
        e.preventDefault();
        setError(null);
        if (!username.trim() || !password) {
            setError({ message: 'Введите имя пользователя и пароль.', field: username.trim() ? 'password' : 'username' });
            return;
        }
        try {
            // Plain axios + storeTokens, like login(): the user is signed in right away.
            await register(username.trim(), password);
            // Same destination rule as the login page: `next` (e.g. /enroll/<id>/) or the
            // dashboard, which shows a one-time "registered" notice.
            if (next) {
                goToNext(next);
            } else {
                navigate('/dashboard/', { state: { justRegistered: true } });
            }
        } catch (err) {
            setError(describeError(err));
        }
    }

    return (
        <div className="page page--form">
            <div className="card auth-card">
                <h1 className="auth-card__title">Регистрация</h1>
                {error && <p id="register-error" className="notice notice-danger auth-card__error" role="alert">{error.message}</p>}
                <form onSubmit={handleSubmit}>
                    <div className="field">
                        <input
                            className="input"
                            type="text"
                            placeholder="Имя пользователя"
                            aria-label="Имя пользователя"
                            autoComplete="username"
                            aria-invalid={error?.field === 'username' ? 'true' : undefined}
                            aria-describedby={error?.field === 'username' ? 'register-error' : undefined}
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
                            aria-invalid={error?.field === 'password' ? 'true' : undefined}
                            aria-describedby={error?.field === 'password' ? 'register-error' : undefined}
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
