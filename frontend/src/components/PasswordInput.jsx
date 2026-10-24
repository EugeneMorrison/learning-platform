import { useState } from 'react';
import './PasswordInput.css';

function EyeIcon({ crossed }) {
    return (
        <svg className="password-input__icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" />
            <circle cx="12" cy="12" r="3" />
            {crossed && <path d="M4 4l16 16" />}
        </svg>
    );
}

/**
 * A password field with an eye button that shows / hides what was typed.
 * Takes the same props as the <input> it renders (className "input" is set
 * here). A mouse click on the eye leaves focus and the caret in the field;
 * keyboard users reach the button with Tab.
 */
function PasswordInput(props) {
    const [visible, setVisible] = useState(false);
    const label = visible ? 'Скрыть пароль' : 'Показать пароль';

    return (
        <div className="password-input">
            <input {...props} className="input password-input__field" type={visible ? 'text' : 'password'} />
            <button
                type="button"
                className="password-input__toggle"
                onClick={() => setVisible(v => !v)}
                onMouseDown={e => e.preventDefault()}
                aria-label={label}
                aria-pressed={visible}
                title={label}
            >
                <EyeIcon crossed={visible} />
            </button>
        </div>
    );
}

export default PasswordInput;
