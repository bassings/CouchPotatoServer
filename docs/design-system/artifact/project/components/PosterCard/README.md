# PosterCard

The library's unit: a 2:3 poster with status and quality badges, a truncated title and the year.

## Use
- Card: `poster-card rounded-md overflow-hidden bg-cp-card border border-white/[0.05] group relative`. Hover adds the `cp-poster-hover` border and `poster-glow` (0.2s).
- Poster: `aspect-[2/3] bg-cp-surface` with a lazy `<img alt="{title}">`; when missing, a `from-cp-card via-cp-surface to-cp-bg` gradient with a thin photo icon and "No poster".
- Status badge top-right (`on-dark`), quality badge over a bottom `from-black/90` gradient.
- Title `text-xs font-medium truncate`; year `text-[10px] text-cp-muted`.
- Hover and `focus-within` reveal a bulk-select checkbox (top-left) and a refresh icon button (bottom-right, `aria-label`). Review cards add "Mark done" / "Mark failed" buttons below.

## The consumer provides
Title, year, poster URL, status, optional quality label, and the movie link.
