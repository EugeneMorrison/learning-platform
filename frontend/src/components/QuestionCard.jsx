import { Link } from 'react-router-dom';
import QuestionContext from './QuestionContext';
import './Question.css';

/**
 * A «Задать вопрос» message in the chat: who asks (full name, else username),
 * course › lesson, the question, the attached task and work (collapsed), and a
 * link to the task in the lesson, which scrolls to it and highlights it.
 *
 * Everything the student typed (the question, the name, and in QuestionContext
 * the code, draft and FILL answers) is rendered as text, never as HTML: a
 * question like <img src=x onerror=alert(1)> shows those characters.
 */
function QuestionCard({ message, own }) {
    const { context } = message;
    return (
        <article className="question-card">
            <p className="question-card__kicker">{context.block.type === 'TEXT' ? 'Вопрос по теории' : 'Вопрос по заданию'}</p>
            {!own && <p className="question-card__who">{message.sender_name || message.sender_username}</p>}
            <p className="question-card__where">{context.course.title} › {context.lesson.title}</p>
            <p className="question-card__text">{message.text}</p>
            <QuestionContext context={context} collapsible />
            <Link className="question-card__open" to={`/lesson/${context.lesson.id}/#block-${context.block.id}`}>
                {context.block.type === 'TEXT' ? 'Открыть теорию →' : 'Открыть задание →'}
            </Link>
        </article>
    );
}

export default QuestionCard;
