<?xml version="1.0" encoding="UTF-8"?>
<!-- Plain dark wallpaper: the theme's background, with a soft glow of
     background_glow slightly above centre that fades out over 85% of the
     screen (smoothstep falloff, approximated by the opacity stops), so the
     edges are the pure theme background. Rendered at build time to
     themes/<name>/backgrounds/00-plain.png by build/render-wallpapers.sh. -->
<svg xmlns="http://www.w3.org/2000/svg" width="3840" height="2160" viewBox="0 0 3840 2160">
  <defs>
    <radialGradient id="g" cx="50%" cy="40%" r="75%">
      <stop offset="0%" stop-color="{{ background_glow }}" stop-opacity="1"/>
      <stop offset="17%" stop-color="{{ background_glow }}" stop-opacity="0.896"/>
      <stop offset="34%" stop-color="{{ background_glow }}" stop-opacity="0.648"/>
      <stop offset="51%" stop-color="{{ background_glow }}" stop-opacity="0.352"/>
      <stop offset="68%" stop-color="{{ background_glow }}" stop-opacity="0.104"/>
      <stop offset="85%" stop-color="{{ background_glow }}" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="3840" height="2160" fill="{{ background }}"/>
  <rect width="3840" height="2160" fill="url(#g)"/>
</svg>
