import CodeMirror from '@uiw/react-codemirror';
import { python } from '@codemirror/lang-python';
import { pycharmDarcula } from './pycharmDarcula';
import { highlightPreBlocks } from '../lib/pythonHighlight';
import { wrapImages } from '../lib/contentImages';
import './Question.css';

// What a «Задать вопрос» message carries (Message.context, built on the server
// in api/questions.py): the task as the student saw it, their latest
// submission and, for CODE, the unsent editor draft. Shown read-only in the
// student's preview (QuestionModal) and on the author's card (QuestionCard).
// Task text is the author's own HTML (as on the lesson page); everything the
// student typed is shown as text.

const READ_ONLY_SETUP = {
    lineNumbers: true,
    foldGutter: false,
    highlightActiveLine: false,
    highlightActiveLineGutter: false,
};

// Same test as QuizBlock: rich-text questions are HTML, older ones plain text.
function isHtml(text) {
    return /<(p|h[1-6]|ul|ol|li|pre|blockquote|img|strong|em|code|div|br)\b/i.test(text || '');
}

function AuthorHtml({ html }) {
    if (!html) return null;
    if (!isHtml(html)) return <p className="question-context__plain">{html}</p>;
    return <div className="text-content" dangerouslySetInnerHTML={{ __html: wrapImages(highlightPreBlocks(html)) }} />;
}

// Python code in the lesson editor's Darcula style, read-only.
export function CodeView({ code }) {
    return (
        <div className="question-code">
            <CodeMirror
                value={code}
                editable={false}
                readOnly
                extensions={[python(), pycharmDarcula]}
                theme="none"
                basicSetup={READ_ONLY_SETUP}
            />
        </div>
    );
}

function Task({ type, task }) {
    if (type === 'QUIZ') {
        return (
            <>
                <AuthorHtml html={task.question} />
                <ol className="question-context__options">
                    {task.options.map((option, i) => <li key={i} dangerouslySetInnerHTML={{ __html: option }} />)}
                </ol>
            </>
        );
    }
    if (type === 'FILL') {
        return (
            <>
                <AuthorHtml html={task.prompt} />
                <pre className="question-context__template">{task.template.replaceAll('{{}}', '____')}</pre>
            </>
        );
    }
    return (
        <>
            <AuthorHtml html={task.prompt} />
            {task.starter_code && (
                <>
                    <p className="question-context__label">Начальный код</p>
                    <CodeView code={task.starter_code} />
                </>
            )}
        </>
    );
}

function Submission({ type, submission }) {
    if (!submission) return <p className="question-context__muted">Решение ещё не отправлялось.</p>;
    const verdict = submission.is_correct === true ? 'Верно' : submission.is_correct === false ? 'Неверно' : null;
    return (
        <>
            {verdict && (
                <p className={submission.is_correct ? 'question-context__verdict question-context__verdict--ok' : 'question-context__verdict'}>
                    {verdict}
                </p>
            )}
            {type === 'CODE' && <CodeView code={submission.code} />}
            {type === 'QUIZ' && (
                submission.option === null
                    ? <p className="question-context__muted">Выбранного варианта больше нет в задании.</p>
                    : <div className="question-context__choice" dangerouslySetInnerHTML={{ __html: submission.option }} />
            )}
            {type === 'FILL' && (
                <ol className="question-context__blanks">
                    {submission.blanks.map((value, i) => <li key={i}><code>{value || '—'}</code></li>)}
                </ol>
            )}
        </>
    );
}

// A titled part: a <details> on the author's card, a plain section in the preview.
function Part({ title, collapsible, children }) {
    if (collapsible) {
        return (
            <details className="question-context__part">
                <summary>{title}</summary>
                <div className="question-context__body">{children}</div>
            </details>
        );
    }
    return (
        <section className="question-context__part">
            <h3 className="question-context__title">{title}</h3>
            <div className="question-context__body">{children}</div>
        </section>
    );
}

function QuestionContext({ context, collapsible = false }) {
    const type = context.block.type;
    return (
        <div className="question-context">
            <Part title="Задание" collapsible={collapsible}>
                <Task type={type} task={context.task} />
            </Part>
            <Part title="Решение студента" collapsible={collapsible}>
                <Submission type={type} submission={context.submission} />
            </Part>
            {context.draft && (
                <Part title="Черновик в редакторе (не отправлялся)" collapsible={collapsible}>
                    <CodeView code={context.draft.code} />
                </Part>
            )}
        </div>
    );
}

export default QuestionContext;
