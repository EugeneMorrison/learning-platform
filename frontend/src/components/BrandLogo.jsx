import { useState } from 'react';
import { BRAND_NAME } from '../brand';

const YO = BRAND_NAME.indexOf('Ё');

function prefersReducedMotion() {
    return Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches);
}

/**
 * The site name (→ landing) with the cat in «Ё»: its dots are the cat's eyes.
 * Styles: the shared /static/public/css/brand-logo.css; the same markup as the
 * Django header (backend/templates/public/includes/brand_logo.html). Hover or
 * keyboard focus plays it once, to the end; a new hover during a play doesn't
 * restart it; reduced motion: never. The text stays the real name.
 *
 * compact: a low header with no room above the letter (the cat grows in place).
 */
function BrandLogo({ className, compact = false }) {
    const [playing, setPlaying] = useState(false);

    if (YO === -1) return <a className={className} href="/">{BRAND_NAME}</a>;

    function play() {
        if (playing || prefersReducedMotion()) return;
        setPlaying(true);
    }

    const classes = [className, 'brand-logo', compact && 'brand-logo--compact', playing && 'is-playing']
        .filter(Boolean).join(' ');

    return (
        <a
            className={classes}
            href="/"
            aria-label={`${BRAND_NAME} — на главную`}
            onMouseEnter={play}
            onFocus={e => { if (e.currentTarget.matches(':focus-visible')) play(); }}
            onAnimationEnd={e => { if (e.animationName === 'brand-cat-face') setPlaying(false); }}
            onAnimationCancel={e => { if (e.animationName === 'brand-cat-face') setPlaying(false); }}
        >
            {BRAND_NAME.slice(0, YO)}
            <span className="brand-logo__yo">
                <span className="brand-logo__letter">Ё</span>
                <span className="brand-logo__cat" aria-hidden="true">
                    <span className="brand-logo__eyes">
                        <span className="brand-logo__eye brand-logo__eye--left" />
                        <span className="brand-logo__eye brand-logo__eye--right" />
                    </span>
                    <svg className="brand-logo__face" viewBox="-60 -45 120 80" focusable="false" aria-hidden="true">
                        <polygon className="brand-logo__ear" points="-36,-14 -30,-33 -14,-19" />
                        <polygon className="brand-logo__ear" points="36,-14 30,-33 14,-19" />
                        <g className="brand-logo__details">
                            <polygon className="brand-logo__nose" points="-4,7 4,7 0,12" />
                            <path className="brand-logo__mouth" d="M-11 13 Q-5.5 22 0 13 Q5.5 22 11 13" />
                            <path
                                className="brand-logo__whiskers"
                                d="M-16 10 L-46 6 M-16 14 L-47 15 M-16 18 L-44 24 M16 10 L46 6 M16 14 L47 15 M16 18 L44 24"
                            />
                        </g>
                    </svg>
                </span>
            </span>
            {BRAND_NAME.slice(YO + 1)}
        </a>
    );
}

export default BrandLogo;
