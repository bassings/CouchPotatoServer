# States

The shared loading, skeleton, empty and error treatments every view reuses.

## Use
- **Spinner**: the shared SVG circle with `animate-spin`, in `text-cp-accent` or `text-cp-muted`, `aria-hidden` beside a text status.
- **Skeleton**: `bg-cp-border` blocks with pulse, shaped like the posters that will load.
- **Empty**: a centred muted icon and one line ("No movies found", "No results found", "Empty folder").
- **Error**: `exclamation-triangle` in `cp-danger-text` plus a one-line message.
- **htmx**: `.htmx-indicator` stays hidden until its request runs.
- All motion collapses under `prefers-reduced-motion: reduce`.

## The consumer provides
The message text and where the state replaces content.
