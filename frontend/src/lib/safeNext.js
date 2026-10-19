// Validation for the ?next= parameter on /login/ and /register/.
//
// Only same-site paths are accepted: the value must start with exactly one "/".
// Rejected (returns null), so they can never become an open redirect:
//   "//evil.com"     protocol-relative URL to another host
//   "/\evil.com"     browsers treat "\" like "/", so this is "//evil.com" too
//   "https://…", "javascript:…", "evil.com", ""   anything not starting with "/"
//   control characters ("/\t/evil.com"): browsers strip tabs/newlines in URLs
export function safeNext(value) {
    if (typeof value !== 'string' || !value.startsWith('/')) return null;
    if (value.startsWith('//') || value.startsWith('/\\')) return null;
    // eslint-disable-next-line no-control-regex
    if (/[\u0000-\u001F\u007F]/.test(value)) return null;
    return value;
}

// After login / sign-up: open `next` with a full page load, not navigate().
// It may be a Django-rendered page (/course/<slug>/ sends anonymous visitors to
// /login/?next=...), which the React router can't show; React routes such as
// /enroll/<id>/ load fine this way too.
export function goToNext(next) {
    window.location.assign(next);
}

// Build "/path/?next=<encoded>" when next is set, else just "/path/".
export function withNext(path, next) {
    return next ? `${path}?next=${encodeURIComponent(next)}` : path;
}
