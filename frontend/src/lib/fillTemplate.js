/**
 * Parse a fill-in-the-blanks template into renderable segments.
 *
 * "print({{8}})" → [{type:'text',value:'print('}, {type:'blank',index:0,answers:['8']}, {type:'text',value:')'}]
 * Blanks are written as {{answer}}; alternatives are separated by | : {{a|b}}.
 * Shared by the viewer (FillBlock) and the editor preview (LessonEditor).
 */
export function parseTemplate(template) {
    const segments = [];
    const re = /\{\{(.*?)\}\}/g;
    let last = 0;
    let blankIndex = 0;
    let m;
    while ((m = re.exec(template || '')) !== null) {
        if (m.index > last) segments.push({ type: 'text', value: template.slice(last, m.index) });
        segments.push({
            type: 'blank',
            index: blankIndex++,
            answers: m[1].split('|').map(s => s.trim()).filter(Boolean),
        });
        last = re.lastIndex;
    }
    if (last < (template || '').length) segments.push({ type: 'text', value: template.slice(last) });
    return segments;
}
