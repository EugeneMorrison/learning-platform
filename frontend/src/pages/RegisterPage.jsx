import { useState } from 'react';
import { useSearchParams, Link } from 'react-router-dom';
import { register } from '../api';
import { safeNext, withNext } from '../lib/safeNext';
import PasswordInput from '../components/PasswordInput';
import ResendConfirmation from '../components/ResendConfirmation';
import './auth.css';

// The Django legal pages (they open in a new tab, so the form keeps its input).
const CONSENT_URL = '/consent/';
const TERMS_URL = '/terms/';
const PRIVACY_POLICY_URL = '/privacy/';

// Two separate required checkboxes, stored separately by the server: the
// personal data consent must be formalised apart from other documents (152-FZ art. 9).
const CONSENT_MESSAGE = 'Чтобы зарегистрироваться, нужно согласие на обработку персональных данных.';
const TERMS_MESSAGE = 'Чтобы зарегистрироваться, нужно принять пользовательское соглашение и политику конфиденциальности.';

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

const FIELD_NAMES = { username: 'имя пользователя', email: 'почту', password: 'пароль' };

// Server error (see register_view in api/auth_views.py) → { message, field }.
// `field` marks the input to highlight: 'username', 'email', 'password', 'consent', 'terms' or null.
function describeError(err) {
    const data = err.response?.data;
    if (!err.response) {
        return { message: 'Нет связи с сервером. Проверьте подключение и попробуйте ещё раз.', field: null };
    }
    if (err.response.status === 429) {
        return { message: 'Слишком много попыток регистрации. Попробуйте позже.', field: null };
    }
    switch (data?.code) {
        case 'required': {
            const names = (data.fields || []).map(name => FIELD_NAMES[name]).filter(Boolean);
            return { message: `Введите ${names.join(', ') || 'все поля'}.`, field: data.fields?.[0] || null };
        }
        case 'consent_required':
            return { message: CONSENT_MESSAGE, field: 'consent' };
        case 'terms_required':
            return { message: TERMS_MESSAGE, field: 'terms' };
        case 'invalid_username':
            return {
                message: 'Имя пользователя может содержать только буквы, цифры и символы @ . + - _ (без пробелов).',
                field: 'username',
            };
        case 'invalid_email':
            return { message: 'Введите правильный адрес почты, например name@example.ru.', field: 'email' };
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
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [acceptConsent, setAcceptConsent] = useState(false);
    const [acceptTerms, setAcceptTerms] = useState(false);
    const [error, setError] = useState(null); // { message, field }
    const [submitting, setSubmitting] = useState(false);
    const [sentTo, setSentTo] = useState(''); // address the confirmation link went to
    const [searchParams] = useSearchParams();
    const next = safeNext(searchParams.get('next'));

    // aria attributes for an input that the current error is about.
    const invalid = field => (error?.field === field
        ? { 'aria-invalid': 'true', 'aria-describedby': 'register-error' }
        : {});

    async function handleSubmit(e) {
        e.preventDefault();
        setError(null);
        const missing = [['username', username.trim()], ['email', email.trim()], ['password', password]]
            .filter(([, value]) => !value).map(([name]) => name);
        if (missing.length) {
            setError({ message: `Введите ${missing.map(name => FIELD_NAMES[name]).join(', ')}.`, field: missing[0] });
            return;
        }
        if (!acceptConsent) {
            setError({ message: CONSENT_MESSAGE, field: 'consent' });
            return;
        }
        if (!acceptTerms) {
            setError({ message: TERMS_MESSAGE, field: 'terms' });
            return;
        }
        setSubmitting(true);
        try {
            // No tokens yet: the account logs in after the emailed link is opened.
            const data = await register({
                username: username.trim(), email: email.trim(), password, acceptConsent, acceptTerms, next,
            });
            setSentTo(data.email);
        } catch (err) {
            setError(describeError(err));
        } finally {
            setSubmitting(false);
        }
    }

    if (sentTo) {
        return (
            <div className="page page--form">
                <div className="card auth-card">
                    <h1 className="auth-card__title">Проверьте почту</h1>
                    <p className="notice notice-success" role="status">
                        Мы отправили письмо на <strong>{sentTo}</strong>. Откройте ссылку из письма,
                        чтобы подтвердить адрес, а затем войдите. Ссылка действует 24 часа.
                    </p>
                    <p className="auth-card__hint">
                        Письма нет? Проверьте папку «Спам» или отправьте его ещё раз.
                    </p>
                    <ResendConfirmation email={sentTo} next={next} />
                    <p className="auth-card__footer">
                        <Link to={withNext('/login/', next)}>Перейти ко входу</Link>
                    </p>
                </div>
            </div>
        );
    }

    return (
        <div className="page page--form">
            <div className="card auth-card">
                <h1 className="auth-card__title">Регистрация</h1>
                {error && <p id="register-error" className="notice notice-danger auth-card__error" role="alert">{error.message}</p>}
                <form onSubmit={handleSubmit} noValidate>
                    <div className="field">
                        <input
                            className="input"
                            type="text"
                            placeholder="Имя пользователя"
                            aria-label="Имя пользователя"
                            autoComplete="username"
                            {...invalid('username')}
                            value={username}
                            onChange={e => setUsername(e.target.value)}
                        />
                    </div>
                    <div className="field">
                        <input
                            className="input"
                            type="email"
                            placeholder="Почта"
                            aria-label="Почта"
                            autoComplete="email"
                            inputMode="email"
                            {...invalid('email')}
                            value={email}
                            onChange={e => setEmail(e.target.value)}
                        />
                    </div>
                    <div className="field">
                        <PasswordInput
                            placeholder="Пароль"
                            aria-label="Пароль"
                            autoComplete="new-password"
                            {...invalid('password')}
                            value={password}
                            onChange={e => setPassword(e.target.value)}
                        />
                    </div>
                    <label className="auth-card__consent">
                        <input
                            type="checkbox"
                            required
                            {...invalid('consent')}
                            checked={acceptConsent}
                            onChange={e => setAcceptConsent(e.target.checked)}
                        />
                        <span>
                            Даю{' '}
                            <a href={CONSENT_URL} target="_blank" rel="noopener noreferrer">
                                согласие на обработку персональных данных
                            </a>
                        </span>
                    </label>
                    <label className="auth-card__consent">
                        <input
                            type="checkbox"
                            required
                            {...invalid('terms')}
                            checked={acceptTerms}
                            onChange={e => setAcceptTerms(e.target.checked)}
                        />
                        <span>
                            Принимаю{' '}
                            <a href={TERMS_URL} target="_blank" rel="noopener noreferrer">
                                пользовательское соглашение
                            </a>
                            {' '}и{' '}
                            <a href={PRIVACY_POLICY_URL} target="_blank" rel="noopener noreferrer">
                                политику конфиденциальности
                            </a>
                        </span>
                    </label>
                    <button type="submit" className="btn btn-primary btn-block" disabled={submitting}>
                        {submitting ? 'Отправляем…' : 'Зарегистрироваться'}
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
