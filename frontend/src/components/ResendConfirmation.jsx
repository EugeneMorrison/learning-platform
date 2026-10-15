import { useState } from 'react';
import { resendConfirmation } from '../api';

/**
 * "Отправить письмо ещё раз": asks the server for a new confirmation link to
 * `email` (POST /api/auth/resend-confirmation/). Used after sign-up and on the
 * login page when the address is not confirmed yet. The server allows 3 per
 * hour per address and per IP.
 */
function ResendConfirmation({ email, next }) {
    const [state, setState] = useState('idle'); // idle | sending | sent | limited | failed

    async function handleClick() {
        setState('sending');
        try {
            await resendConfirmation(email, next);
            setState('sent');
        } catch (err) {
            setState(err.response?.status === 429 ? 'limited' : 'failed');
        }
    }

    return (
        <div className="auth-card__resend">
            <button type="button" className="btn btn-secondary btn-block" onClick={handleClick}
                    disabled={state === 'sending' || state === 'limited'}>
                {state === 'sending' ? 'Отправляем…' : 'Отправить письмо ещё раз'}
            </button>
            <p className="auth-card__hint" role="status">
                {state === 'sent' && 'Новое письмо отправлено. Предыдущие ссылки тоже действуют, пока не истекли.'}
                {state === 'limited' && 'Слишком много запросов. Попробуйте ещё раз через час.'}
                {state === 'failed' && 'Не удалось отправить письмо. Попробуйте ещё раз.'}
            </p>
        </div>
    );
}

export default ResendConfirmation;
