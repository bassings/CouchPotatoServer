# NavItem

A sidebar link: 16px outline Heroicon plus a 13px label, with a tinted active state.

## Use
- `flex items-center gap-3 px-3 py-2 rounded text-[13px] font-medium transition-colors`.
- Inactive: `text-cp-muted hover:text-cp-text hover:bg-white/[0.03]`. Active: `bg-cp-accent/10 text-cp-accent` plus `aria-current="page"`.
- Lives in the `cp-chrome` sidebar (`sidebar-width`, collapsing to `sidebar-collapsed` with labels fading out) under the brand row: `couch.png` at 28px and "CouchPotato" in Inter 600. Below `lg` the same items appear in a bottom nav, icon over label.

## The consumer provides
The route, label and the Heroicon path; the shell sets the active state from `current_page`.
