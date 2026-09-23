# ReleaseTable

The movie-detail list of found releases, with size and seeder health.

## Use
- `table.w-full.text-xs`; header row `border-b border-white/[0.05] text-cp-muted`, headers `px-4 py-2.5 font-medium text-[10px] uppercase tracking-wider` with `scope="col"`.
- Data rows `border-b border-white/[0.03] hover:bg-white/[0.015]`; cells `px-4 py-2.5`.
- Size and seeders in `font-mono font-light text-cp-muted`; seeder colour by health (success / muted / warning).
- NZB rows leave seeders blank, not 0, with an `sr-only` label: "0" would read as a dead torrent.
- Mark failed uses the danger button; in dark it takes `cp-danger-strong` text.

## The consumer provides
Rows of release name, quality, size, seeders (or none) and the per-row action.
