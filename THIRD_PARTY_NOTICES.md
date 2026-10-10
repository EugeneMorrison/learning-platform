# Third-party notices

This project includes or depends on the third-party software and fonts listed
below. Each remains under its own licence; the full licence texts are in the
locations noted, or in the package itself (`node_modules/<package>/LICENSE`,
or the installed Python distribution's metadata).

Last reviewed: 2026-10-10.

## Fonts (distributed with the site)

All fonts are self-hosted; the site makes no requests to remote font services.

| Font | Weights shipped | Where | Licence | Licence file |
|---|---|---|---|---|
| Unbounded | 500, 700 (cyrillic, latin, latin-ext subsets) | `backend/static/public/fonts/` — public Django pages, headings | SIL Open Font License 1.1 — Copyright 2022 The Unbounded Project Authors (https://github.com/googlefonts/unbounded) | `backend/static/public/fonts/Unbounded-OFL.txt` |
| Golos Text | 400, 500, 700 (cyrillic, latin, latin-ext subsets) | `backend/static/public/fonts/` — public Django pages, body text | SIL Open Font License 1.1 — Copyright 2019 The Golos Text Project Authors (https://github.com/googlefonts/golos-text) | `backend/static/public/fonts/GolosText-OFL.txt` |
| JetBrains Mono | 400, 600 (official v2.304 webfonts) | `frontend/public/fonts/jetbrains-mono/` — code in the React app | SIL Open Font License 1.1 — Copyright 2020 The JetBrains Mono Project Authors (https://github.com/JetBrains/JetBrainsMono) | `frontend/public/fonts/jetbrains-mono/JetBrainsMono-OFL.txt` |
| JetBrains Mono | 400 (same official file) | `backend/static/public/fonts/` — code card in the landing hero | SIL Open Font License 1.1 — as above | `backend/static/public/fonts/JetBrainsMono-OFL.txt` |

None of these fonts declares a Reserved Font Name. The Unbounded and Golos Text
files are per-script subsets (from the Fontsource packages); JetBrains Mono files
are unmodified from the official repository.

Fallback fonts named in CSS (`system-ui`, `-apple-system`, `BlinkMacSystemFont`,
`Segoe UI`, `Roboto`, `Arial`, `Consolas`, `Courier New`, generic `sans-serif` /
`monospace`) are the visitor's own system fonts and are not distributed by us.

## Frontend dependencies (bundled into the React app)

| Package | Version | Licence |
|---|---|---|
| @codemirror/lang-python | 6.2.1 | MIT |
| @codemirror/language | 6.12.3 | MIT |
| @codemirror/view | 6.43.0 | MIT |
| @lezer/highlight | 1.2.3 | MIT |
| @tiptap/extension-image | 3.26.0 | MIT |
| @tiptap/pm | 3.26.0 | MIT |
| @tiptap/react | 3.26.0 | MIT |
| @tiptap/starter-kit | 3.26.0 | MIT |
| @uiw/react-codemirror | 4.25.10 | MIT |
| axios | 1.20.0 | MIT |
| highlight.js | 11.11.1 | BSD-3-Clause |
| react | 19.2.4 | MIT |
| react-dom | 19.2.4 | MIT |
| react-router-dom | 7.18.4 | MIT |

Build and lint tools (not shipped to visitors): @eslint/js, @types/react,
@types/react-dom, @vitejs/plugin-react, eslint, eslint-plugin-react-hooks,
eslint-plugin-react-refresh, globals, vite — all MIT.

## Backend dependencies (`requirements.txt`, run on the server)

| Package | Version | Licence |
|---|---|---|
| asgiref | 3.11.1 | BSD-3-Clause |
| Django | 6.0.3 | BSD-3-Clause |
| django-cors-headers | 4.9.0 | MIT |
| django-filter | 25.2 | BSD |
| djangorestframework | 3.16.1 | BSD |
| djangorestframework_simplejwt | 5.5.1 | MIT |
| PyJWT | 2.12.0 | MIT |
| sqlparse | 0.5.5 | BSD |
| tzdata | 2025.3 | Apache-2.0 |
| beautifulsoup4 | 4.13.4 | MIT |
| channels | 4.3.2 | BSD |
| daphne | 4.2.2 | BSD |
| whitenoise | 6.9.0 | MIT |
| python-slugify | 9.1.2 | MIT |
| Pillow | 12.3.0 | MIT-CMU (HPND) |

Note on a transitive dependency: python-slugify uses **text-unidecode 1.3**,
which is dual-licensed under the Artistic License or GPLv2+. This project uses it
under the Artistic License, on the server only (it is not distributed to visitors).
