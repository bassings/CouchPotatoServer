# Badge

Small lowercase pills that name a movie's status or a release's quality.

## Use
- Base: `px-1.5 py-0.5 rounded text-[9px] font-medium`.
- On flat surfaces: wanted `bg-cp-blue/20 text-cp-blue`, done `bg-cp-success/20 text-cp-success`, snatched `bg-cp-warning/20 text-cp-warning`. In light the text darkens automatically (`cp-accent-text`, `cp-success-text`, `cp-warning-text`).
- Over poster art or its `from-black/90` gradient: add `on-dark` so the text keeps the bright base colour; quality is `bg-white/10 text-white/80 backdrop-blur-sm`.
- Directly on artwork (downloaded / review): solid `bg-cp-warning text-black` (9.4:1). A same-hue tint cannot reach 4.5:1 over real posters at any opacity.

## The consumer provides
The status word (lowercase) and where it sits: flat surface or artwork.
