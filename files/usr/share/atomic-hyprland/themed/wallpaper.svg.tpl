<?xml version="1.0" encoding="UTF-8"?>
<!-- Plain dark wallpaper: a radial gradient from the theme's background_glow
     at the centre to its background at the edges. Rendered at build time to
     themes/<name>/backgrounds/00-plain.png by build/render-wallpapers.sh. -->
<svg xmlns="http://www.w3.org/2000/svg" width="3840" height="2160" viewBox="0 0 3840 2160">
  <defs>
    <radialGradient id="g" cx="50%" cy="40%" r="75%">
      <stop offset="0%" stop-color="{{ background_glow }}"/>
      <stop offset="60%" stop-color="{{ background }}"/>
      <stop offset="100%" stop-color="{{ background }}"/>
    </radialGradient>
  </defs>
  <rect width="3840" height="2160" fill="url(#g)"/>
</svg>
