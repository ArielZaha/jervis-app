// The weather window's map, built only from sources that are free to use, with no account and no key:
//   base map   OpenFreeMap vector tiles (OpenStreetMap data): roads, coastlines, borders, towns and cities. Free with
//              no limits, commercial use allowed. Its "dark" style is recoloured here to Jervis's navy.
//   terrain    Mapzen terrain tiles on AWS Open Data, drawn as soft hillshading so hills and valleys read
//   radar      RainViewer's latest rain-radar frames, as a loop (free for personal use; tiles exist up to zoom 7 and
//              are scaled up beyond that, which is what radar resolution allows anyway)
// Drawn with MapLibre GL (BSD licence, bundled in vendor/maplibre, so the map code itself never depends on a server).
// Place names sit above the rain. If a source can't be reached the map says so; the rest of the window doesn't
// depend on it.
(function () {
  const STYLE_URL = 'https://tiles.openfreemap.org/styles/dark';
  const TERRAIN_TILES = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png';
  const RADAR_MAX_ZOOM = 7;
  const HOME_ZOOM = 8.5;
  const ATTRIBUTION = 'OpenFreeMap © OpenMapTiles · Data © OpenStreetMap contributors · Terrain: Mapzen (SRTM, GMTED)';
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const BASE = document.currentScript ? new URL('..', document.currentScript.src).href : '';

  // Jervis's palette for the map: deep navy land, a slightly lifted sea, quiet roads, readable names.
  const C = {
    background: '#0a1426', water: '#0f2546', waterway: '#143059', landcover: '#0c1830', park: '#0d1d33',
    landuse: '#0c172a', building: '#0f1c33', buildingEdge: '#16263f', minor: '#18294a', major: '#203759',
    motorway: '#2a4877', casing: 'rgba(79,216,255,0.10)', rail: '#1a2a45', boundary: 'rgba(143,178,222,0.38)',
    label: '#b7c7e1', labelMajor: '#e2ebf8', halo: 'rgba(5,10,20,0.88)', roadLabel: '#6a7fa3', waterLabel: '#5583b6',
  };

  let libraryPromise = null;
  function loadMapLibre() {
    if (window.maplibregl) return Promise.resolve(window.maplibregl);
    if (!libraryPromise) {
      libraryPromise = new Promise((resolve, reject) => {
        const css = document.createElement('link');
        css.rel = 'stylesheet';
        css.href = `${BASE}vendor/maplibre/maplibre-gl.css`;
        document.head.append(css);
        // Jervis's window has Node enabled, which makes the bundle export through require instead of a global.
        if (typeof require === 'function') {
          try { resolve(require('./vendor/maplibre/maplibre-gl.js')); return; } catch (e) { /* fall back to a tag */ }
        }
        const script = document.createElement('script');
        script.src = `${BASE}vendor/maplibre/maplibre-gl.js`;
        script.onload = () => (window.maplibregl ? resolve(window.maplibregl) : reject(new Error('MapLibre missing')));
        script.onerror = () => reject(new Error('MapLibre could not be loaded'));
        document.head.append(script);
      });
    }
    return libraryPromise;
  }

  function recolour(style) {
    for (const layer of style.layers) {
      const p = (layer.paint = layer.paint || {});
      const id = layer.id;
      if (layer.type === 'background') p['background-color'] = C.background;
      else if (id === 'water') p['fill-color'] = C.water;
      else if (id === 'waterway') p['line-color'] = C.waterway;
      else if (id.startsWith('landcover')) p['fill-color'] = C.landcover;
      else if (id === 'landuse_park') p['fill-color'] = C.park;
      else if (id.startsWith('landuse')) p['fill-color'] = C.landuse;
      else if (id === 'building') { p['fill-color'] = C.building; p['fill-outline-color'] = C.buildingEdge; }
      else if (layer.type === 'symbol') {
        p['text-halo-color'] = C.halo;
        p['text-halo-width'] = 1.3;
        p['text-color'] = id === 'water_name' ? C.waterLabel : id.startsWith('highway_name') ? C.roadLabel
          : /city|country|state/.test(id) ? C.labelMajor : C.label;
      } else if (/casing/.test(id)) p['line-color'] = C.casing;
      else if (/motorway_inner/.test(id)) p['line-color'] = C.motorway;
      else if (/major_inner|major_subtle/.test(id)) p['line-color'] = C.major;
      else if (/railway/.test(id)) p['line-color'] = id.includes('dash') ? C.background : C.rail;
      else if (/boundary/.test(id)) p['line-color'] = C.boundary;
      else if (/highway|aeroway|road_/.test(id) && (layer.type === 'line' || layer.type === 'fill')) p[`${layer.type}-color`] = C.minor;
    }
    // soft terrain shading, under the roads and names
    style.sources.terrain = { type: 'raster-dem', tiles: [TERRAIN_TILES], encoding: 'terrarium', tileSize: 256, maxzoom: 14 };
    const at = style.layers.findIndex((l) => l.id === 'waterway');
    style.layers.splice(at < 0 ? 1 : at, 0, {
      id: 'terrain-shade', type: 'hillshade', source: 'terrain',
      paint: { 'hillshade-exaggeration': 0.45, 'hillshade-shadow-color': '#02060f',
        'hillshade-highlight-color': 'rgba(150,190,240,0.16)', 'hillshade-accent-color': '#0a1426' },
    });
    return style;
  }

  class WeatherMap {
    constructor(root) {
      this.root = root;
      root.classList.add('wxm');
      root.innerHTML = `
        <div class="wxm-viewport" tabindex="0" aria-label="Weather map. Drag or use the arrow keys to move, plus and minus to zoom."></div>
        <div class="wxm-haze" aria-hidden="true"></div>
        <div class="wxm-vignette" aria-hidden="true"></div>
        <div class="wxm-zoom" role="group" aria-label="Zoom">
          <button type="button" class="wxm-btn" data-zoom="1" aria-label="Zoom in">+</button>
          <button type="button" class="wxm-btn" data-zoom="-1" aria-label="Zoom out">−</button>
          <button type="button" class="wxm-btn wxm-home" aria-label="Back to my location" title="Back to the location">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="3.5"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/></svg>
          </button>
        </div>
        <div class="wxm-radar" hidden>
          <button type="button" class="wxm-play" aria-label="Pause the radar loop" aria-pressed="true">
            <svg class="i-pause" viewBox="0 0 24 24" fill="currentColor"><rect x="7" y="6" width="3.6" height="12" rx="1"/><rect x="13.4" y="6" width="3.6" height="12" rx="1"/></svg>
            <svg class="i-play" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5.5v13l10.5-6.5z"/></svg>
          </button>
          <div class="wxm-radar-meta"><span class="wxm-radar-title">Rain radar</span><b class="wxm-radar-time">—</b></div>
          <ol class="wxm-ticks" aria-hidden="true"></ol>
          <span class="wxm-scale" title="Light to heavy rain"><i></i></span>
        </div>
        <p class="wxm-note" hidden></p>
        <p class="wxm-attrib"></p>`;
      this.viewport = root.querySelector('.wxm-viewport');
      this.markerEl = document.createElement('div');
      this.markerEl.className = 'wxm-marker';
      this.markerEl.innerHTML = '<i></i><i></i><b></b><span class="wxm-pin-label"></span>';
      this.map = null;
      this.home = null;
      this.radar = null;
      this.frame = 0;
      this.playing = true;
      this.tileErrors = 0;
      this.bindControls();
      this.attribution();
      new ResizeObserver(() => this.map?.resize()).observe(this.viewport);
    }

    // ---------- public ----------
    setLocation(lat, lon, label) {
      this.home = [lon, lat];
      this.setLabel(label);
      if (this.map) {
        this.map.jumpTo({ center: this.home, zoom: HOME_ZOOM });
        this.marker?.setLngLat(this.home);
        return;
      }
      this.create();
    }

    setLabel(label) { this.markerEl.querySelector('.wxm-pin-label').textContent = label || ''; }

    setCloudCover(percent) {
      this.root.style.setProperty('--haze', Math.max(0, Math.min(1, (percent || 0) / 100)).toFixed(2));
    }

    setRadar(radar) {
      this.stopRadar();
      this.radar = radar && radar.frames && radar.frames.length ? radar : null;
      this.root.querySelector('.wxm-radar').hidden = !this.radar;
      this.attribution();
      this.note(this.radar ? '' : 'Rain radar is unavailable right now.');
      if (!this.radar) { this.clearRadarLayers(); return; }
      this.root.querySelector('.wxm-ticks').innerHTML = this.radar.frames.map(() => '<li></li>').join('');
      this.frame = this.radar.frames.length - 1;   // start on the latest
      if (this.styleReady) this.addRadarLayers();
      this.showFrame(this.frame);
      if (this.playing && !reduced.matches) this.playRadar();
      else this.setPlaying(false);
    }

    start() { if (this.radar && this.playing && !reduced.matches) this.playRadar(); }
    stop() { this.stopRadar(); }

    // ---------- the map ----------
    async create() {
      let maplibregl, style;
      try {
        maplibregl = await loadMapLibre();
        const response = await fetch(STYLE_URL);
        if (!response.ok) throw new Error(`map style: HTTP ${response.status}`);
        style = recolour(await response.json());
      } catch (e) {
        console.warn(`Weather map unavailable: ${e.message}`);
        this.root.classList.add('wxm-offline');
        this.note('The map couldn’t load (no connection to the free map service).');
        return;
      }
      if (this.map) return;
      try {
        this.map = new maplibregl.Map({
          container: this.viewport, style, center: this.home, zoom: HOME_ZOOM, minZoom: 3, maxZoom: 14,
          attributionControl: false, dragRotate: false, pitchWithRotate: false, touchPitch: false, maxPitch: 0,
          fadeDuration: reduced.matches ? 0 : 250,
        });
      } catch (e) {   // no WebGL
        console.warn(`Weather map unavailable: ${e.message}`);
        this.root.classList.add('wxm-offline');
        this.note('This computer can’t draw the map (WebGL is unavailable).');
        return;
      }
      this.map.touchZoomRotate.disableRotation();
      this.marker = new maplibregl.Marker({ element: this.markerEl, anchor: 'center' }).setLngLat(this.home).addTo(this.map);
      this.map.on('load', () => {
        this.styleReady = true;
        if (this.radar) { this.addRadarLayers(); this.showFrame(this.frame); }
      });
      this.map.on('error', (event) => {
        if (++this.tileErrors === 12) this.note('Some map tiles couldn’t load. Check the internet connection.');
        if (this.tileErrors < 4) console.warn('Weather map:', event?.error?.message || event);
      });
    }

    labelsAbove() {
      // radar goes over the roads but under the place and road names
      const layers = this.map.getStyle().layers;
      return (layers.find((l) => l.type === 'symbol' && (l.id.startsWith('highway_name') || l.id.startsWith('place_'))) || {}).id;
    }

    clearRadarLayers() {
      if (!this.map || !this.styleReady) return;
      for (const layer of this.map.getStyle().layers.filter((l) => l.id.startsWith('radar-'))) {
        this.map.removeLayer(layer.id);
        this.map.removeSource(layer.id);
      }
    }

    addRadarLayers() {
      this.clearRadarLayers();
      const before = this.labelsAbove();
      this.radar.frames.forEach((frame, i) => {
        const id = `radar-${i}`;
        this.map.addSource(id, { type: 'raster', tiles: [`${this.radar.host}${frame.path}/256/{z}/{x}/{y}/2/1_1.png`],
          tileSize: 256, maxzoom: RADAR_MAX_ZOOM });
        this.map.addLayer({ id, type: 'raster', source: id, paint: { 'raster-opacity': 0, 'raster-fade-duration': 0,
          'raster-opacity-transition': { duration: reduced.matches ? 0 : 400 } } }, before);
      });
    }

    note(text) {
      const n = this.root.querySelector('.wxm-note');
      n.textContent = text;
      n.hidden = !text;
    }

    attribution() {
      this.root.querySelector('.wxm-attrib').textContent = this.radar ? `${ATTRIBUTION} · Radar: RainViewer` : ATTRIBUTION;
    }

    // ---------- radar animation ----------
    showFrame(i) {
      this.frame = i;
      if (this.map && this.styleReady) {
        this.radar.frames.forEach((_f, j) => {
          if (this.map.getLayer(`radar-${j}`)) this.map.setPaintProperty(`radar-${j}`, 'raster-opacity', j === i ? 0.78 : 0);
        });
      }
      [...this.root.querySelectorAll('.wxm-ticks li')].forEach((li, j) => li.classList.toggle('on', j <= i));
      const t = new Date(this.radar.frames[i].time * 1000);
      this.root.querySelector('.wxm-radar-time').textContent =
        t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + (i === this.radar.frames.length - 1 ? ' · latest' : '');
    }

    playRadar() {
      this.stopRadar();
      this.setPlaying(true);
      const tick = () => {
        const last = this.frame === this.radar.frames.length - 1;
        this.showFrame(last ? 0 : this.frame + 1);
        this.radarTimer = setTimeout(tick, this.frame === this.radar.frames.length - 1 ? 1600 : 600);
      };
      this.radarTimer = setTimeout(tick, 900);
    }

    stopRadar() { clearTimeout(this.radarTimer); }

    setPlaying(on) {
      this.playing = on;
      const btn = this.root.querySelector('.wxm-play');
      btn.setAttribute('aria-pressed', String(on));
      btn.setAttribute('aria-label', on ? 'Pause the radar loop' : 'Play the radar loop');
      btn.classList.toggle('paused', !on);
    }

    bindControls() {
      this.root.querySelectorAll('[data-zoom]').forEach((b) => b.addEventListener('click', () => {
        if (!this.map) return;
        if (Number(b.dataset.zoom) > 0) this.map.zoomIn(); else this.map.zoomOut();
      }));
      this.root.querySelector('.wxm-home').addEventListener('click', () => {
        if (this.map && this.home) this.map.easeTo({ center: this.home, zoom: HOME_ZOOM, duration: reduced.matches ? 0 : 600 });
      });
      this.root.querySelector('.wxm-play').addEventListener('click', () => {
        if (!this.radar) return;
        if (this.playing) { this.stopRadar(); this.setPlaying(false); } else this.playRadar();
      });
    }
  }

  WeatherMap.recolour = recolour;
  window.WeatherMap = WeatherMap;
})();
