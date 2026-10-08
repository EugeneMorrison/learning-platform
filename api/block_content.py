"""
Block content as students see it, and server-side grading.

The course author gets a block's full `content`. Everyone else who can read the
block (enrolled students) gets `student_content()`: no answers, no hidden tests.
Grading (QUIZ, FILL here; CODE in RunTestsView) happens only on the server, and
`feedback()` decides what a student may learn from their own answer.

Answer-bearing fields per type:
- CODE: `solution`; `tests` (each {input, expected, visible?}, or a legacy string
  meaning expected output with empty stdin).
- QUIZ: `correct_answer` (option index), `explanation`.
- FILL: the answers inside `{{a|b}}` in `template`, `explanation`.
"""

import re

# Gap markers in FILL templates. Same pattern as the frontend's parseTemplate():
# non-greedy, no newlines inside a gap.
FILL_GAP_RE = re.compile(r'\{\{(.*?)\}\}')

# When no test in a CODE block carries a `visible` flag, the first N are visible.
DEFAULT_VISIBLE_TESTS = 2


# -----------------------------------------------------------------------------
# CODE tests
# -----------------------------------------------------------------------------

def normalize_test(test):
    """(stdin, expected) for a test; legacy string tests are expected output only."""
    if isinstance(test, dict):
        return test.get('input', '') or '', test.get('expected', '') or ''
    return '', test or ''


def test_visibility(tests):
    """One bool per test: explicit `visible` flags if any test has one, else the
    first DEFAULT_VISIBLE_TESTS are visible (so existing and imported blocks work)."""
    tests = tests or []
    if any(isinstance(t, dict) and 'visible' in t for t in tests):
        return [isinstance(t, dict) and t.get('visible') is True for t in tests]
    return [i < DEFAULT_VISIBLE_TESTS for i in range(len(tests))]


# -----------------------------------------------------------------------------
# Student view of content
# -----------------------------------------------------------------------------

def student_content(block_type, content):
    """A copy of `content` without anything that reveals answers."""
    content = dict(content or {})
    if block_type == 'CODE':
        tests = content.get('tests') or []
        flags = test_visibility(tests)
        content.pop('solution', None)
        content['tests'] = [t for t, visible in zip(tests, flags) if visible]
        content['hidden_test_count'] = flags.count(False)
    elif block_type == 'QUIZ':
        content.pop('correct_answer', None)
        content.pop('explanation', None)
    elif block_type == 'FILL':
        content['template'] = FILL_GAP_RE.sub('{{}}', content.get('template', '') or '')
        content.pop('explanation', None)
    return content


# -----------------------------------------------------------------------------
# Grading (QUIZ, FILL)
# -----------------------------------------------------------------------------

def grade_quiz(content, answer):
    selected = answer.get('selected') if isinstance(answer, dict) else None
    return selected is not None and selected == content.get('correct_answer')


def fill_blank_results(content, answer):
    """One bool per gap, or [] when the answer doesn't have one value per gap.

    Gaps are {{answer}} or {{a|b}} (alternatives); compared trimmed and, unless
    content['case_sensitive'], case-insensitively.
    """
    gaps = FILL_GAP_RE.findall(content.get('template', '') or '')
    submitted = answer.get('blanks') if isinstance(answer, dict) else None
    if not gaps or not isinstance(submitted, list) or len(submitted) != len(gaps):
        return []
    case_sensitive = content.get('case_sensitive', False)
    results = []
    for raw, sub in zip(gaps, submitted):
        accepted = [a.strip() for a in raw.split('|') if a.strip()]
        value = str(sub or '').strip()
        if not case_sensitive:
            value = value.lower()
            accepted = [a.lower() for a in accepted]
        results.append(value in accepted)
    return results


def grade_fill(content, answer):
    results = fill_blank_results(content, answer)
    return bool(results) and all(results)


def feedback(block_type, content, answer, is_correct):
    """What a student may see about their own answer. The explanation only after
    a correct answer; for FILL also which gaps are right (never the answers)."""
    result = {}
    if block_type == 'FILL':
        result['blanks_correct'] = fill_blank_results(content, answer)
    if block_type in ('QUIZ', 'FILL') and is_correct and content.get('explanation'):
        result['explanation'] = content['explanation']
    return result
