# Your elvish config: created once by the image, never written again.
set E:EDITOR = hx
if (has-external starship) { eval (starship init elvish) }

# Homebrew (/home/linuxbrew), appended after the system paths so the
# image's own tools win when both have one.
use os
if (os:exists /home/linuxbrew/.linuxbrew/bin/brew) {
  set-env HOMEBREW_PREFIX /home/linuxbrew/.linuxbrew
  set-env HOMEBREW_CELLAR /home/linuxbrew/.linuxbrew/Cellar
  set-env HOMEBREW_REPOSITORY /home/linuxbrew/.linuxbrew/Homebrew
  set paths = [$@paths /home/linuxbrew/.linuxbrew/bin /home/linuxbrew/.linuxbrew/sbin]
}
