# Toast

Transient top-right confirmation of what just happened, from the global Alpine `toast(message, type, duration)` queue.

## Use
- Call `toast(msg, 'success' | 'error' | 'info', 3000)` inside Alpine, or dispatch `window.dispatchEvent(new CustomEvent('cp-toast', {detail: {message, type}}))` from plain JS.
- Fills: success `bg-green-700 cp-toast-fg`, error `bg-red-700 cp-toast-fg`, info `bg-cp-accent text-black`, `rounded-lg`. The 700 weights and `.cp-toast-fg` are required for 4.5:1; `text-white` is repainted in light and fails.
- Auto-dismiss after 3000ms plus a manual close button.

## Accessibility
Toast nodes are `aria-hidden`. The shell's two persistent `sr-only` live regions (polite; assertive for errors) announce the message, cleared then set so a repeated message is re-announced.

## The consumer provides
A short past-tense or status message; never interactive content.
