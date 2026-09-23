# Modal

A centred dialog for focused tasks: folder browsing, movie info, confirmations.

## Use
- Scrim `fixed inset-0 z-50 bg-black/60` (`cp-scrim`); panel `bg-cp-card rounded-xl border border-white/[0.05] w-full max-w-lg max-h-[80vh] flex flex-col`.
- Header (title + close X with `aria-label="Close"`), scrollable body, footer with right-aligned Cancel (ghost) then primary.
- Required: `role="dialog" aria-modal="true"` labelled by its title; Escape closes, scrim click dismisses, Tab is trapped, focus returns to the trigger.
- The directory browser adds an Up button, a mono path (`cp-surface` strip) and a folder list. The restart banner is a related fixed bottom-centre bar in `bg-cp-warning/20 border-cp-warning/30`.

## The consumer provides
Title, body content, and the primary action's label and handler.
