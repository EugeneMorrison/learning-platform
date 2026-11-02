import { useState } from 'react';

// Stable account and block IDs keep drafts separate on shared browsers. Auth
// tokens rotate and disappear on logout, so they must not identify a draft.
function draftKey(userId, blockId) {
    if (userId == null || blockId == null) return null;
    return `code-draft:v1:${encodeURIComponent(userId)}:${encodeURIComponent(blockId)}`;
}

export default function useCodeDraft(userId, blockId, fallbackCode) {
    const key = draftKey(userId, blockId);
    const [draft, setDraft] = useState(() => {
        try {
            if (!key) throw new Error('Draft owner is unavailable');
            return {
                code: localStorage.getItem(key) ?? fallbackCode,
                storageAvailable: true,
            };
        } catch {
            return { code: fallbackCode, storageAvailable: false };
        }
    });

    function updateCode(code) {
        let storageAvailable = false;
        try {
            if (key) {
                // Write in the editor event itself: a navigation or reload must
                // not beat a debounce timer, effect, or unload handler.
                localStorage.setItem(key, code);
                storageAvailable = true;
            }
        } catch {
            // Storage can be disabled or full; keep the editor usable and let
            // the student know this change could not be preserved.
        }
        setDraft({ code, storageAvailable });
    }

    return [draft.code, updateCode, draft.storageAvailable];
}
