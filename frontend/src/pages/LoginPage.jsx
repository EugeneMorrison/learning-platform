import { useState } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { login } from '../api';
import { goToNext, safeNext, withNext } from '../lib/safeNext';
import PasswordInput from '../components/PasswordInput';
import ResendConfirmation from '../components/ResendConfirmation';
import './auth.css';

// Result of the emailed confirmation link: /login/?confirm=... (confirm_email_view).
const CONFIRM_NOTICES = {
    ok: { kind: 'success', text: 'Адрес почты подтверждён. Теперь войдите.' },
    used: { kind: 'success', text: 'Адрес почты уже подтверждён. Просто войдите.' },
    expired: { kind: 'warning', text: 'Ссылка устарела: она действует 24 часа. Войдите, и мы предложим отправить новое письмо.' },
    invalid: { kind: 'danger', text: 'Ссылка недействительна. Скопируйте её из письма целиком или войдите, чтобы получить новую.' },
};

function LoginPage() {
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [unconfirmedEmail, setUnconfirmedEmail] = useState(''); // password ok, address not confirmed
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const next = safeNext(searchParams.get('next'));
    const confirmNotice = CONFIRM_NOTICES[searchParams.get('confirm')];

    async function handleSubmit(e) {
        e.preventDefault();
        setError('');
        setUnconfirmedEmail('');
        try {
            await login(username, password);
            if (next) {
                goToNext(next);
            } else {
                // First login right after the emailed link: the dashboard shows a
                // one-time "registered" notice.
                navigate('/dashboard/', searchParams.get('confirm') === 'ok' ? { state: { justRegistered: true } } : undefined);
            }
        } catch (err) {
            const data = err.response?.data;
            if (data?.code === 'email_not_verified') {
                setUnconfirmedEmail(data.email);
            } else if (!err.response) {
                setError('Нет связи с сервером. Проверьте подключение и попробуйте ещё раз.');
            } else {
                setError('Неверный логин или пароль');
            }
        }
    }

    return (
        <div className="page page--form">
            <div className="card auth-card">
                <h1 className="auth-card__title">Вход</h1>
                {confirmNotice && !error && !unconfirmedEmail && (
                    <p className={`notice notice-${confirmNotice.kind} auth-card__error`} role="status">{confirmNotice.text}</p>
                )}
                {error && <p className="notice notice-danger auth-card__error" role="alert">{error}</p>}
                {unconfirmedEmail && (
                    <div className="auth-card__error">
                        <p className="notice notice-warning" role="alert">
                            Подтвердите адрес почты: откройте ссылку из письма, которое мы отправили
                            на <strong>{unconfirmedEmail}</strong>.
                        </p>
                        <ResendConfirmation email={unconfirmedEmail} next={next} />
                    </div>
                )}
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
                        <PasswordInput
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
