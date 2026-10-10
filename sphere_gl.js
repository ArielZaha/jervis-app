// A textured, lit sphere drawn on the GPU (WebGL 2) for the distance globe and the planet models: every screen pixel
// is shaded at full resolution with mipmapped texture sampling, so the surface stays sharp at any size or zoom.
// The caller draws the result onto its own 2D canvas (stars, arcs, pins and labels stay 2D). Returns null where
// WebGL 2 isn't available, and the caller falls back to its CPU painter.
//
// The view is an orthographic projection of a unit sphere, seen from OUTSIDE (east to the right of west), turned by
// a longitude spin and then a latitude tilt — the same two rotations project() uses in earth.js / planet.js.
(function () {
  const VERT = `#version 300 es
in vec2 aPos;
void main() { gl_Position = vec4(aPos, 0.0, 1.0); }`;

  const FRAG = `#version 300 es
precision highp float;
out vec4 outColor;
uniform sampler2D uDay, uClouds, uNight;
uniform float uHasClouds, uHasNight, uEarth, uCloudDrift, uRadius, uEmissive, uAmbient;
uniform vec2 uTerm;            // the twilight band, as the sun's dot product: where light fades out and fully in
uniform vec2 uCenter;          // in device pixels, origin bottom-left (gl_FragCoord)
uniform vec4 uRot;             // cos/sin of the longitude spin, cos/sin of the latitude tilt
uniform vec3 uLight;           // the fixed "sun", in screen space (x right, y up, z toward the viewer)
uniform vec3 uRim;             // atmosphere colour
const float PI = 3.14159265358979;

// Equirectangular maps wrap at longitude 180: derivatives taken across that seam would pick the smallest mip level
// and draw a visible line, so the gradient is taken on whichever of two shifted parameterisations is continuous here.
vec4 sampleWrapped(sampler2D t, vec2 uv) {
  vec2 dx = dFdx(uv), dy = dFdy(uv);
  vec2 shifted = vec2(fract(uv.x + 0.5), uv.y);
  vec2 dx2 = dFdx(shifted), dy2 = dFdy(shifted);
  if (abs(dx2.x) + abs(dy2.x) < abs(dx.x) + abs(dy.x)) { dx = dx2; dy = dy2; }
  return textureGrad(t, vec2(fract(uv.x), uv.y), dx, dy);
}

void main() {
  vec2 p = (gl_FragCoord.xy - uCenter) / uRadius;          // -1..1 across the disc, y up
  float r = length(p);
  float aa = max(fwidth(r), 1e-4) * 1.2;
  float inside = 1.0 - smoothstep(1.0 - aa, 1.0, r);
  if (inside <= 0.0) discard;
  float pz = sqrt(max(0.0, 1.0 - r * r));
  vec3 n = vec3(p, pz);                                      // the surface normal, screen space

  // Undo the view's two rotations to find which point of the body's own surface faces this pixel. The x axis is
  // negated: seen from outside, east lies to the right (the earlier painter showed the globe mirrored).
  float mx = -p.x;
  float y1 = p.y * uRot.z + pz * uRot.w;
  float z1 = -p.y * uRot.w + pz * uRot.z;
  float x = mx * uRot.x + z1 * uRot.y;
  float z = -mx * uRot.y + z1 * uRot.x;
  float lon = atan(z, x) + PI * 0.5;
  float lat = asin(clamp(y1, -1.0, 1.0));
  vec2 uv = vec2((lon + PI) / (2.0 * PI), (PI * 0.5 - lat) / PI);

  vec3 day = sampleWrapped(uDay, uv).rgb;
  float lum = dot(day, vec3(0.299, 0.587, 0.114));
  day = mix(vec3(lum), day, uEarth > 0.5 ? 1.12 : 1.05);    // a touch more vivid than the flat source photo

  float ndl = dot(n, uLight);
  float lit = smoothstep(uTerm.x, uTerm.y, ndl);            // a soft terminator, not a hard line
  vec3 color = day * (uAmbient + (1.08 - uAmbient) * lit);
  if (uEmissive > 0.5) {                                     // a star shines by itself: no night side, darker limb
    color = day * (0.55 + 0.75 * pow(pz, 0.45)) * vec3(1.1, 1.0, 0.92);
    ndl = 1.0;
  }

  if (uEarth > 0.5) {
    // Oceans (deep and shelf blues in the Blue Marble imagery) get the sun's glint; land and ice don't.
    float ocean = smoothstep(0.03, 0.12, day.b - max(day.r, day.g * 0.92));
    vec3 h = normalize(uLight + vec3(0.0, 0.0, 1.0));
    float spec = pow(max(dot(n, h), 0.0), 70.0) * 0.85 + pow(max(dot(n, h), 0.0), 12.0) * 0.12;
    color += vec3(1.0, 0.97, 0.9) * spec * ocean * lit;
    if (uHasNight > 0.5) {                                   // city lights on the night side
      vec3 night = sampleWrapped(uNight, uv).rgb;
      float dark = 1.0 - smoothstep(uTerm.x - 0.08, uTerm.y * 0.4, ndl);
      color += pow(night, vec3(1.4)) * vec3(1.0, 0.82, 0.55) * dark * 1.6;
    }
    if (uHasClouds > 0.5) {
      vec2 cuv = vec2(uv.x + uCloudDrift, uv.y);
      float c = sampleWrapped(uClouds, cuv).r;
      c = smoothstep(0.22, 0.95, c);
      color *= 1.0 - 0.22 * c * lit;                          // the clouds' own shade on the ground beneath
      vec3 cloudCol = vec3(1.0) * (0.08 + 1.0 * lit);
      color = mix(color, cloudCol, c * 0.78);
    }
  }

  // The atmosphere: a thin, bright rim where you look through the most air, brightest on the sunlit side.
  float fres = pow(1.0 - pz, 2.6);
  color += uRim * fres * (0.25 + 0.9 * smoothstep(-0.3, 0.6, ndl));
  color = color / (1.0 + 0.12 * color);                     // gentle highlight roll-off instead of clipping
  outColor = vec4(color * inside, inside);
}`;

  function createSphereRenderer() {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl2', { premultipliedAlpha: true, alpha: true, antialias: false, preserveDrawingBuffer: true });
    if (!gl) return null;
    const compile = (type, src) => {
      const s = gl.createShader(type);
      gl.shaderSource(s, src); gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
      return s;
    };
    const prog = gl.createProgram();
    try {
      gl.attachShader(prog, compile(gl.VERTEX_SHADER, VERT));
      gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, FRAG));
      gl.linkProgram(prog);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
    } catch (e) {
      console.warn('Sphere shader failed, using the CPU painter:', e);
      return null;
    }
    gl.useProgram(prog);
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, 'aPos');
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    const U = {};
    ['uDay', 'uClouds', 'uNight', 'uHasClouds', 'uHasNight', 'uEarth', 'uCloudDrift', 'uRadius', 'uCenter', 'uRot', 'uLight', 'uRim', 'uEmissive', 'uAmbient', 'uTerm']
      .forEach((name) => { U[name] = gl.getUniformLocation(prog, name); });
    gl.uniform1i(U.uDay, 0); gl.uniform1i(U.uClouds, 1); gl.uniform1i(U.uNight, 2);
    const anisotropy = gl.getExtension('EXT_texture_filter_anisotropic');

    const textures = {};   // url -> {tex, ready}
    const blank = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, blank);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([12, 20, 36, 255]));

    function texture(url, onReady) {
      if (!url) return null;
      if (textures[url]) {
        const known = textures[url];
        if (onReady) known.ready ? onReady() : known.waiters.push(onReady);
        return known;
      }
      const entry = { tex: gl.createTexture(), ready: false, waiters: onReady ? [onReady] : [] };
      textures[url] = entry;
      const img = new Image();
      img.onload = () => {
        gl.bindTexture(gl.TEXTURE_2D, entry.tex);
        gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
        gl.generateMipmap(gl.TEXTURE_2D);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        if (anisotropy) gl.texParameterf(gl.TEXTURE_2D, anisotropy.TEXTURE_MAX_ANISOTROPY_EXT,
          Math.min(8, gl.getParameter(anisotropy.MAX_TEXTURE_MAX_ANISOTROPY_EXT)));
        entry.ready = true;
        entry.waiters.splice(0).forEach((fn) => fn());
      };
      img.onerror = () => console.warn(`Sphere imagery failed to load (${url}).`);
      img.src = url;
      return entry;
    }

    /** Draws the sphere into this renderer's own canvas, sized w x h device pixels, and returns that canvas.
     *  v: {cx, cy, R (device px, y down), cLon, sLon, cLat, sLat, light: [x, y, z], day, clouds, night, earth,
     *      cloudDrift, rim: [r, g, b]} */
    function draw(w, h, v) {
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      gl.viewport(0, 0, w, h);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      const day = texture(v.day), clouds = texture(v.clouds), night = texture(v.night);
      const bind = (unit, entry) => { gl.activeTexture(gl.TEXTURE0 + unit); gl.bindTexture(gl.TEXTURE_2D, entry && entry.ready ? entry.tex : blank); };
      bind(0, day); bind(1, clouds); bind(2, night);
      gl.uniform1f(U.uHasClouds, clouds && clouds.ready ? 1 : 0);
      gl.uniform1f(U.uHasNight, night && night.ready ? 1 : 0);
      gl.uniform1f(U.uEarth, v.earth ? 1 : 0);
      gl.uniform1f(U.uEmissive, v.emissive ? 1 : 0);
      gl.uniform1f(U.uAmbient, v.ambient == null ? 0.06 : v.ambient);
      const term = v.terminator || [-0.18, 0.42];
      gl.uniform2f(U.uTerm, term[0], term[1]);
      gl.uniform1f(U.uCloudDrift, v.cloudDrift || 0);
      gl.uniform1f(U.uRadius, v.R);
      gl.uniform2f(U.uCenter, v.cx, h - v.cy);
      gl.uniform4f(U.uRot, v.cLon, v.sLon, v.cLat, v.sLat);
      const L = v.light, n = Math.hypot(L[0], L[1], L[2]);
      gl.uniform3f(U.uLight, L[0] / n, L[1] / n, L[2] / n);
      const rim = v.rim || [0.35, 0.62, 1.0];
      gl.uniform3f(U.uRim, rim[0], rim[1], rim[2]);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      return canvas;
    }

    const ready = (url) => Boolean(textures[url] && textures[url].ready);
    return { draw, texture, ready, canvas };
  }

  window.createSphereRenderer = createSphereRenderer;
})();
