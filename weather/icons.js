// Jarvis weather icons: one small, consistent set (sun, moon, cloud, rain, snow, storm, fog) drawn as inline SVG, so
// they're crisp at any size and tinted to match the window. `animated` adds slow, quiet motion (turning rays, falling
// drops) for the one big icon in the weather window; every other icon is still.
(function () {
  let uid = 0;

  function sun(id, cx, cy, r) {
    const rays = [];
    for (let i = 0; i < 8; i++) {
      const a = (i * Math.PI) / 4;
      const x1 = cx + Math.cos(a) * (r + 5), y1 = cy + Math.sin(a) * (r + 5);
      const x2 = cx + Math.cos(a) * (r + 10), y2 = cy + Math.sin(a) * (r + 10);
      rays.push(`<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}"/>`);
    }
    return `<g class="wxi-sun">
      <g class="wxi-rays" style="transform-origin:${cx}px ${cy}px" stroke="url(#${id}s)" stroke-width="2.6" stroke-linecap="round">${rays.join('')}</g>
      <circle cx="${cx}" cy="${cy}" r="${r}" fill="url(#${id}s)"/>
    </g>`;
  }

  function moon(id, cx, cy, r) {
    return `<g class="wxi-moon"><path d="M${cx + r * 0.35} ${cy - r} a${r} ${r} 0 1 0 ${r * 0.65} ${r * 1.55} a${r * 0.8} ${r * 0.8} 0 0 1 -${r * 0.65} -${r * 1.55}z" fill="url(#${id}m)"/></g>`;
  }

  // A cloud built from circles over a flat base, so it reads at 20px and at 140px.
  function cloud(id, x, y, s, dim) {
    return `<g class="wxi-cloud" transform="translate(${x} ${y}) scale(${s})">
      <path d="M14 38h34a11 11 0 0 0 1.5-21.9A15 15 0 0 0 21 13.4 10.5 10.5 0 0 0 14 38z" fill="url(#${id}${dim ? 'd' : 'c'})"/>
      <path d="M14 38h34a11 11 0 0 0 1.5-21.9A15 15 0 0 0 21 13.4 10.5 10.5 0 0 0 14 38z" fill="none" stroke="rgba(255,255,255,.55)" stroke-width=".8"/>
    </g>`;
  }

  function drops(kind) {
    if (kind === 'snow') {
      return `<g class="wxi-snow" fill="#e6f3ff">${[[22, 50], [32, 55], [42, 50], [27, 59], [37, 61]].map(([x, y], i) =>
        `<circle cx="${x}" cy="${y}" r="1.9" style="animation-delay:${i * 0.35}s"/>`).join('')}</g>`;
    }
    const heavy = kind === 'rain' || kind === 'storm';
    const lines = heavy ? [[22, 47], [30, 50], [38, 47], [46, 50]] : [[25, 48], [35, 50], [45, 48]];
    return `<g class="wxi-rain" stroke="#5ec8ff" stroke-width="2.2" stroke-linecap="round">${lines.map(([x, y], i) =>
      `<line x1="${x}" y1="${y}" x2="${x - 2.5}" y2="${y + (heavy ? 8 : 5)}" style="animation-delay:${i * 0.22}s"/>`).join('')}</g>`;
  }

  function wxIcon(kind, isDay = true, opts = {}) {
    const id = `wxi${++uid}`;
    const night = isDay === false;
    const defs = `<defs>
      <linearGradient id="${id}s" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffe29a"/><stop offset="1" stop-color="#ffb347"/></linearGradient>
      <linearGradient id="${id}m" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#f4f1ff"/><stop offset="1" stop-color="#a9b4ff"/></linearGradient>
      <linearGradient id="${id}c" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#b9cbe4"/></linearGradient>
      <linearGradient id="${id}d" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#c9d5e6"/><stop offset="1" stop-color="#7f90ab"/></linearGradient>
    </defs>`;
    let body;
    switch (kind) {
      case 'clear':
        body = night ? moon(id, 30, 31, 15) : sun(id, 32, 32, 11);
        break;
      case 'partly':
        body = (night ? moon(id, 24, 22, 11) : sun(id, 24, 22, 8.5)) + cloud(id, 10, 14, 0.82);
        break;
      case 'cloudy':
        body = cloud(id, 0, 2, 0.7, true) + cloud(id, 6, 10, 0.86);
        break;
      case 'fog':
        body = cloud(id, 4, 0, 0.86, true) + `<g class="wxi-fog" stroke="#c7d3e6" stroke-width="2.4" stroke-linecap="round">
          <line x1="12" y1="44" x2="52" y2="44"/><line x1="18" y1="51" x2="46" y2="51" opacity=".7"/><line x1="14" y1="58" x2="40" y2="58" opacity=".45"/></g>`;
        break;
      case 'drizzle': case 'rain': case 'snow':
        body = cloud(id, 4, -2, 0.86, kind !== 'drizzle') + drops(kind);
        break;
      case 'storm':
        body = cloud(id, 4, -2, 0.86, true) + drops('rain').replace('wxi-rain', 'wxi-rain wxi-faint') +
          `<path class="wxi-bolt" d="M35 38l-7 12h6l-4 11 11-15h-6l4-8z" fill="#ffd166" stroke="#fff3c4" stroke-width=".6" stroke-linejoin="round"/>`;
        break;
      default:
        body = cloud(id, 6, 6, 0.86);
    }
    const cls = `wxi${opts.animated ? ' wxi-anim' : ''}`;
    return `<svg class="${cls}" viewBox="0 0 64 64" aria-hidden="true" focusable="false">${defs}${body}</svg>`;
  }

  window.wxIcon = wxIcon;
})();
