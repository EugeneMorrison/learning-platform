import { useEffect, useRef, useState } from 'react';
import api from '../api';

export default function CourseExport({ courseId }) {
    const [authorMaterials, setAuthorMaterials] = useState(false);
    const [busy, setBusy] = useState(false);
    const [status, setStatus] = useState('');
    const [error, setError] = useState('');
    const active = useRef(null);
    useEffect(() => () => active.current?.abort(), []);

    async function download(format) {
        if (active.current) return;
        const controller = new AbortController();
        active.current = controller;
        const config = { signal: controller.signal };
        const base = '/courses/' + courseId + '/exports/';
        setBusy(true);
        setError('');
        setStatus('Готовим файл…');
        try {
            const file = await api.post(base, {
                format, author_materials: format === 'zip' && authorMaterials,
            }, {
                ...config, responseType: 'blob', timeout: 400000,
                onDownloadProgress: ({ progress }) => {
                    if (!controller.signal.aborted && progress != null) {
                        setStatus('Скачиваем файл… ' + Math.round(progress * 100) + '%');
                    }
                },
            });
            const href = URL.createObjectURL(file.data);
            const link = document.createElement('a');
            link.href = href;
            const disposition = file.headers['content-disposition'] || '';
            const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i);
            const plain = disposition.match(/filename="([^"]+)"/i);
            link.download = encoded ? decodeURIComponent(encoded[1]) : plain?.[1] || ('course-' + courseId + '.' + format);
            document.body.appendChild(link);
            link.click();
            link.remove();
            setTimeout(() => URL.revokeObjectURL(href), 1000);
            setStatus('Файл передан браузеру для сохранения.');
        } catch (err) {
            if (controller.signal.aborted) return;
            setStatus('');
            let details = err.response?.data;
            if (details instanceof Blob) {
                try { details = JSON.parse(await details.text()); } catch { details = null; }
            }
            const detail = details?.detail;
            const message = err.isAxiosError ? 'Не удалось скачать курс. Попробуйте ещё раз.' : err.message;
            setError(typeof detail === 'string' ? detail : message);
        } finally {
            active.current = null;
            if (!controller.signal.aborted) setBusy(false);
        }
    }

    return (
        <section aria-label="Экспорт курса">
            <h2>Экспорт курса</h2>
            <div className="course-level">
                <button type="button" className="btn btn-secondary btn-sm" disabled={busy}
                    onClick={() => download('mhtml')}>Скачать MHTML</button>
                <button type="button" className="btn btn-secondary btn-sm" disabled={busy}
                    onClick={() => download('zip')}>Скачать STEP (ZIP)</button>
                <label><input type="checkbox" checked={authorMaterials} disabled={busy}
                    onChange={event => setAuthorMaterials(event.target.checked)} /> Включить решения автора и скрытые тесты в STEP (ZIP)</label>
            </div>
            <p role="status">{status}</p>
            {error && <p role="alert">{error}</p>}
        </section>
    );
}
