import './CourseCover.css';

/**
 * A course card's cover in the app (dashboard «Мои курсы»): the public
 * cards' look (public/includes/course_cover.html, components.css) — a 4:3
 * box on --color-cover, the image multiplied onto it (white backgrounds turn
 * grey), or the cobalt block with the title's first letter when there is no
 * cover. Decorative: the card's title says which course it is.
 */
function CourseCover({ title, cover }) {
    return (
        <div className="course-thumb">
            {cover ? (
                <img className="course-thumb__img" src={cover} alt="" width="640" height="480" loading="lazy" />
            ) : (
                <div className="course-thumb__fallback" aria-hidden="true">
                    {(title || '').trim().charAt(0).toUpperCase()}
                </div>
            )}
        </div>
    );
}

export default CourseCover;
