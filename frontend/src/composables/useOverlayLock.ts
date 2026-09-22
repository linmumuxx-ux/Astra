let count = 0

// Reference-counted body scroll lock so several stacked dialogs never release
// the lock while another one is still open.
export function acquireOverlayLock(): void {
  count += 1
  document.body.classList.add('overlay-open')
}

export function releaseOverlayLock(): void {
  count = Math.max(0, count - 1)
  if (count === 0) document.body.classList.remove('overlay-open')
}

export function resetOverlayLock(): void {
  count = 0
  document.body.classList.remove('overlay-open')
}