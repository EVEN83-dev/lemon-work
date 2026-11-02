/*
 * Lemon Code 3D 海洋壁纸 — 零依赖 WebGL1 版
 * 兼容 QWebEngine / Chromium 69：无 WebGPU、无 CDN、无框架、无可选链语法。
 * 渲染：全屏四边形 + 光线步进高度场海浪 + 解析天空（白天湛蓝 / 夕阳玫瑰红 / 黑夜暗橙浪+月光+星空）。
 * 对外协议与 WebGPU 版一致：window.__ocean = { setMode, setSeaState, pause, resume, cleanup }
 * 以及 postMessage { type:'oceanMode', mode } 桥接、oceanReady / oceanError 信号。
 */
(function () {
  'use strict';

  var canvas = document.getElementById('glcanvas');

  function notifyParent(type) {
    try {
      if (window.parent && window.parent !== window) {
        window.parent.postMessage({ type: type }, '*');
      }
    } catch (e) { /* ignore */ }
  }

  var gl = canvas.getContext('webgl', { antialias: false, alpha: false, powerPreference: 'low-power' })
        || canvas.getContext('experimental-webgl', { antialias: false, alpha: false });
  if (!gl) {
    notifyParent('oceanError');
    return;
  }
  canvas.addEventListener('webglcontextlost', function (e) {
    e.preventDefault();
    notifyParent('oceanError');
  });

  // ---------------- Shaders ----------------

  var VERT_SRC = [
    'attribute vec2 aPos;',
    'void main() { gl_Position = vec4(aPos, 0.0, 1.0); }'
  ].join('\n');

  var FRAG_SRC = [
    'precision highp float;',
    '',
    'uniform vec2 uRes;',
    'uniform float uTime;',
    'uniform float uSea;',
    'uniform vec3 uSunDir;',
    'uniform vec3 uMoonDir;',
    'uniform float uNight;',
    'uniform vec3 uZenith;',
    'uniform vec3 uHorizon;',
    'uniform vec3 uSunColor;',
    'uniform vec3 uDeep;',
    'uniform vec3 uShallow;',
    'uniform vec3 uSssSun;',
    'uniform vec3 uSssMoonA;',
    'uniform vec3 uSssMoonB;',
    'uniform vec3 uFoam;',
    'uniform vec3 uSunGlit;',
    'uniform vec3 uMoonGlit;',
    'uniform vec3 uCloudTint;',
    'uniform int uSteps;',
    'uniform float uYaw;',
    '',
    'float hash21(vec2 p) {',
    '  p = fract(p * vec2(123.34, 456.21));',
    '  p += dot(p, p + 45.32);',
    '  return fract(p.x * p.y);',
    '}',
    '',
    'float vnoise(vec2 p) {',
    '  vec2 i = floor(p);',
    '  vec2 f = fract(p);',
    '  vec2 u = f * f * (3.0 - 2.0 * f);',
    '  float a = hash21(i);',
    '  float b = hash21(i + vec2(1.0, 0.0));',
    '  float c = hash21(i + vec2(0.0, 1.0));',
    '  float d = hash21(i + vec2(1.0, 1.0));',
    '  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);',
    '}',
    '',
    'float fbm(vec2 p) {',
    '  float v = 0.0;',
    '  float amp = 0.5;',
    '  for (int i = 0; i < 3; i++) {',
    '    v += vnoise(p) * amp;',
    '    p *= 2.03;',
    '    amp *= 0.5;',
    '  }',
    '  return v;',
    '}',
    '',
    'float waveH(vec2 p, float t) {',
    '  float h = 0.0;',
    '  h += 0.30 * sin(dot(p, vec2(0.28, 0.10)) + t * 0.90);',
    '  h += 0.22 * sin(dot(p, vec2(-0.16, 0.26)) + t * 1.15);',
    '  h += 0.15 * sin(dot(p, vec2(0.42, -0.30)) + t * 0.75);',
    '  h += 0.09 * sin(dot(p, vec2(-0.55, -0.18)) + t * 1.35);',
    '  h += 0.55 * (fbm(p * 0.10 + t * 0.05) - 0.5);',
    '  h += 0.22 * (fbm(p * 0.35 - t * 0.08) - 0.5);',
    '  return h * uSea;',
    '}',
    '',
    'vec3 skyColor(vec3 d) {',
    '  float elev = d.y;',
    '  float t = smoothstep(-0.08, 0.7, elev);',
    '  vec3 sky = mix(uHorizon, uZenith, t);',
    '',
    '  float sunDot = max(dot(d, uSunDir), 0.0);',
    '  float sunDisc = smoothstep(0.9982, 0.9997, sunDot);',
    '  float sunGlow = pow(sunDot, 65.0) * 0.55;',
    '  sky += uSunColor * (sunDisc + sunGlow);',
    '',
    '  float moonDot = max(dot(d, uMoonDir), 0.0);',
    '  float moonDisc = smoothstep(0.9993, 0.99975, moonDot);',
    '  float moonHalo = pow(moonDot, 300.0) * 0.4;',
    '  sky += (vec3(0.92, 0.95, 1.0) * moonDisc + vec3(0.55, 0.62, 0.75) * moonHalo) * uNight;',
    '',
    '  vec2 cuv = d.xz / max(abs(elev), 0.05) * 0.35 + uTime * 0.008;',
    '  float cn = fbm(cuv);',
    '  float band = sin(length(d.xz) * 14.0 + cn * 3.0) * 0.5 + 0.5;',
    '  float cmask = smoothstep(0.44, 0.72, band) * clamp(1.0 - abs(elev) * 2.2, 0.0, 1.0) * (1.0 - uNight);',
    '  sky += uCloudTint * cmask * 0.8;',
    '',
    '  vec3 cell = floor(d * 260.0);',
    '  float sh = hash21(cell.xz + cell.y * 17.0);',
    '  float star = smoothstep(0.992, 0.998, sh) * uNight * smoothstep(0.02, 0.2, elev);',
    '  sky += vec3(0.85, 0.92, 1.0) * star;',
    '',
    '  return sky;',
    '}',
    '',
    'vec3 waveNormal(vec2 p, float t, float h0) {',
    '  float e = 0.10;',
    '  float hx = waveH(p + vec2(e, 0.0), t) - h0;',
    '  float hz = waveH(p + vec2(0.0, e), t) - h0;',
    '  return normalize(vec3(-hx / e, 1.0, -hz / e));',
    '}',
    '',
    'void main() {',
    '  vec2 uv = (gl_FragCoord.xy * 2.0 - uRes) / uRes.y;',
    '  vec3 fwd = vec3(sin(uYaw), 0.0, -cos(uYaw));',
    '  vec3 rgt = vec3(cos(uYaw), 0.0, sin(uYaw));',
    '  vec3 d = normalize(fwd * 1.6 + rgt * uv.x + vec3(0.0, 1.0, 0.0) * (uv.y - 0.10));',
    '  vec3 o = vec3(0.0, 1.7, 0.0);',
    '',
    '  vec3 col;',
    '  if (d.y >= -0.015) {',
    '    col = skyColor(d);',
    '  } else {',
    '    float t = 0.0;',
    '    float prevT = 0.0;',
    '    bool hit = false;',
    '    for (int i = 0; i < 28; i++) {',
    '      if (i >= uSteps) break;',
    '      vec3 p = o + d * t;',
    '      float h = waveH(p.xz, uTime);',
    '      float dh = p.y - h;',
    '      if (dh < 0.0) { hit = true; break; }',
    '      prevT = t;',
    '      t += clamp(dh * 0.8, 0.06, 3.0);',
    '      if (t > 90.0) break;',
    '    }',
    '    if (!hit) {',
    '      col = skyColor(d);',
    '    } else {',
    '      float tA = prevT;',
    '      float tB = t;',
    '      for (int j = 0; j < 5; j++) {',
    '        float tm = (tA + tB) * 0.5;',
    '        vec3 pm = o + d * tm;',
    '        if (pm.y < waveH(pm.xz, uTime)) { tB = tm; } else { tA = tm; }',
    '      }',
    '      float th = (tA + tB) * 0.5;',
    '      vec3 p = o + d * th;',
    '      float h0 = waveH(p.xz, uTime);',
    '      vec3 n = waveNormal(p.xz, uTime, h0);',
    '      vec3 v = normalize(o - p);',
    '      vec3 r = reflect(d, n);',
    '      r.y = abs(r.y);',
    '',
    '      float hFac = clamp(h0 * 0.9 + 0.5, 0.0, 1.0);',
    '      vec3 base = mix(uDeep, uShallow, hFac);',
    '',
    '      float sunN = max(dot(n, uSunDir), 0.0);',
    '      float moonN = max(dot(n, uMoonDir), 0.0);',
    '      float crest = clamp(h0, 0.0, 1.0);',
    '      vec3 sssMoonCol = mix(uSssMoonA, uSssMoonB, clamp(h0 * 0.5 + 0.5, 0.0, 1.0));',
    '      vec3 sss = (pow(sunN, 2.0) * uSssSun + pow(moonN, 1.6) * sssMoonCol * 1.2) * crest;',
    '',
    '      float foamN = fbm(p.xz * 0.8 + uTime * 0.15);',
    '      float foamM = smoothstep(0.55, 0.9, h0 + foamN * 0.2 - 0.1);',
    '',
    '      vec3 lit = base + sss + foamM * uFoam;',
    '',
    '      vec3 skyR = skyColor(r);',
    '      float fres = 0.08 + 0.85 * pow(1.0 - max(dot(n, v), 0.0), 3.0);',
    '      vec3 col2 = mix(lit, skyR, fres);',
    '',
    '      float sunSpec = pow(max(dot(r, uSunDir), 0.0), 160.0) * 1.8 * smoothstep(-0.1, 0.4, uSunDir.y);',
    '      float moonSpec = pow(max(dot(r, uMoonDir), 0.0), 220.0) * 1.3 * uNight;',
    '      col2 += uSunGlit * sunSpec + uMoonGlit * moonSpec;',
    '',
    '      float dist = length(p - o);',
    '      float fog = 1.0 - exp(-dist * 0.022);',
    '      col2 = mix(col2, uHorizon, clamp(fog, 0.0, 0.9));',
    '      col = col2;',
    '    }',
    '  }',
    '',
    '  col = col * (2.51 * col + 0.03) / (col * (2.43 * col + 0.59) + 0.14);',
    '  float vig = 1.0 - 0.22 * length(uv * vec2(0.6, 0.8));',
    '  col *= clamp(vig, 0.0, 1.0);',
    '  gl_FragColor = vec4(col, 1.0);',
    '}'
  ].join('\n');

  function compile(type, src) {
    var s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
      gl.deleteShader(s);
      return null;
    }
    return s;
  }

  var vs = compile(gl.VERTEX_SHADER, VERT_SRC);
  var fs = compile(gl.FRAGMENT_SHADER, FRAG_SRC);
  if (!vs || !fs) {
    notifyParent('oceanError');
    return;
  }
  var prog = gl.createProgram();
  gl.attachShader(prog, vs);
  gl.attachShader(prog, fs);
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
    notifyParent('oceanError');
    return;
  }
  gl.useProgram(prog);

  var buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  var locPos = gl.getAttribLocation(prog, 'aPos');
  gl.enableVertexAttribArray(locPos);
  gl.vertexAttribPointer(locPos, 2, gl.FLOAT, false, 0, 0);

  var U = {};
  ['uRes', 'uTime', 'uSea', 'uSunDir', 'uMoonDir', 'uNight', 'uZenith', 'uHorizon',
   'uSunColor', 'uDeep', 'uShallow', 'uSssSun', 'uSssMoonA', 'uSssMoonB', 'uFoam',
   'uSunGlit', 'uMoonGlit', 'uCloudTint', 'uSteps', 'uYaw'].forEach(function (name) {
    U[name] = gl.getUniformLocation(prog, name);
  });

  // ---------------- State & palettes ----------------

  var params = new URLSearchParams(location.search);
  var fpsLimit = parseInt(params.get('fps') || '60', 10);
  if (!isFinite(fpsLimit)) fpsLimit = 60;
  fpsLimit = Math.min(144, Math.max(24, fpsLimit));

  var state = {
    timeOfDay: 2.0,
    targetTimeOfDay: 2.0,
    seaState: 0.6,
    targetSeaState: 0.6
  };

  function smoothstep(e0, e1, x) {
    var t = Math.min(1, Math.max(0, (x - e0) / (e1 - e0)));
    return t * t * (3 - 2 * t);
  }
  function clamp01(x) { return Math.min(1, Math.max(0, x)); }
  function mix3(a, b, t) {
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
  }
  function mix4(a, b, c, wa, wb, wc) {
    return [
      a[0] * wa + b[0] * wb + c[0] * wc,
      a[1] * wa + b[1] * wb + c[1] * wc,
      a[2] * wa + b[2] * wb + c[2] * wc
    ];
  }

  // 调色板：day / sunset / night
  var PAL = {
    zenith:   { day: [0.00, 0.45, 1.00], sunset: [0.35, 0.23, 0.43], night: [0.006, 0.006, 0.035] },
    horizon:  { day: [0.65, 0.84, 1.00], sunset: [0.88, 0.26, 0.42], night: [0.030, 0.050, 0.120] },
    sunColor: { day: [1.00, 0.98, 0.90], sunset: [1.00, 0.56, 0.42], night: [0.000, 0.000, 0.000] },
    deep:     { day: [0.00, 0.06, 0.15], sunset: [0.10, 0.04, 0.12], night: [0.102, 0.051, 0.031] },
    shallow:  { day: [0.00, 0.34, 0.45], sunset: [0.30, 0.12, 0.20], night: [0.230, 0.105, 0.050] },
    sssSun:   { day: [0.38, 0.58, 0.48], sunset: [0.85, 0.35, 0.42], night: [0.000, 0.000, 0.000] },
    sssMoonA: { day: [0.00, 0.00, 0.00], sunset: [0.00, 0.00, 0.00], night: [0.541, 0.290, 0.125] },
    sssMoonB: { day: [0.00, 0.00, 0.00], sunset: [0.00, 0.00, 0.00], night: [0.761, 0.400, 0.122] },
    foam:     { day: [0.94, 0.98, 1.00], sunset: [1.00, 0.62, 0.60], night: [0.500, 0.300, 0.150] },
    sunGlit:  { day: [1.00, 0.96, 0.85], sunset: [1.00, 0.56, 0.42], night: [0.000, 0.000, 0.000] },
    moonGlit: { day: [0.00, 0.00, 0.00], sunset: [0.00, 0.00, 0.00], night: [0.810, 0.850, 0.910] },
    cloudTint:{ day: [0.95, 0.98, 1.00], sunset: [1.00, 0.60, 0.62], night: [0.350, 0.380, 0.500] }
  };

  var PRESETS = {
    day: { tod: 12.0, sea: 1.0 },
    sunset: { tod: 17.8, sea: 1.2 },
    night: { tod: 2.0, sea: 0.6 }
  };

  // ---------------- Sizing / DPR / degrade ----------------

  var dprCap = 1.25;
  var degradeLevel = 0; // 0 无 | 1 DPR=1 | 2 步进28→16 | 3 DPR=0.8
  var steps = 28;

  function resize() {
    var dpr = Math.min(window.devicePixelRatio || 1, dprCap);
    if (degradeLevel === 1) dpr = Math.min(dpr, 1);
    if (degradeLevel >= 3) dpr = Math.min(dpr, 0.8);
    var w = Math.max(1, Math.floor(canvas.clientWidth * dpr));
    var h = Math.max(1, Math.floor(canvas.clientHeight * dpr));
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
      gl.viewport(0, 0, w, h);
    }
  }
  window.addEventListener('resize', resize);

  // ---------------- Render loop ----------------

  var rafId = 0;
  var running = true;
  var visible = true;
  var lastRenderAt = 0;
  var startTime = performance.now();
  var lastFrameAt = startTime;
  var frameCount = 0;
  var fpsAccum = 0;
  var lowFpsWindows = 0;

  document.addEventListener('visibilitychange', function () {
    visible = document.visibilityState === 'visible';
  });

  function frame() {
    rafId = requestAnimationFrame(frame);
    if (!running || !visible) return;

    var now = performance.now();
    if (now - lastRenderAt < 1000 / fpsLimit - 0.5) return;
    var dt = (now - lastRenderAt) / 1000;
    lastRenderAt = now;

    // 平滑过渡（时间/浪高向目标插值）
    var k = Math.min(1, dt * 2.2);
    state.timeOfDay += (state.targetTimeOfDay - state.timeOfDay) * k;
    state.seaState += (state.targetSeaState - state.seaState) * k;

    var t = (now - startTime) / 1000;

    // 太阳 / 月亮方向
    var ang = (state.timeOfDay - 6) / 12 * Math.PI;
    var sx = Math.cos(ang), sy = Math.sin(ang), sz = 0.25;
    var sl = Math.sqrt(sx * sx + sy * sy + sz * sz);
    sx /= sl; sy /= sl; sz /= sl;
    var mx = -sx + 0.18, my = -sy + 0.30, mz = -sz + 0.12;
    var ml = Math.sqrt(mx * mx + my * my + mz * mz);
    mx /= ml; my /= ml; mz /= ml;

    // 三态权重
    var wDay = smoothstep(0.06, 0.25, sy);
    var wNight = 1 - smoothstep(-0.18, -0.06, sy);
    var wSunset = clamp01(1 - wDay - wNight);

    function pal(name) {
      var p = PAL[name];
      return mix4(p.day, p.sunset, p.night, wDay, wSunset, wNight);
    }

    resize();
    gl.uniform2f(U.uRes, canvas.width, canvas.height);
    gl.uniform1f(U.uTime, t);
    gl.uniform1f(U.uSea, state.seaState);
    gl.uniform3f(U.uSunDir, sx, sy, sz);
    gl.uniform3f(U.uMoonDir, mx, my, mz);
    gl.uniform1f(U.uNight, wNight);
    gl.uniform3fv(U.uZenith, pal('zenith'));
    gl.uniform3fv(U.uHorizon, pal('horizon'));
    gl.uniform3fv(U.uSunColor, pal('sunColor'));
    gl.uniform3fv(U.uDeep, pal('deep'));
    gl.uniform3fv(U.uShallow, pal('shallow'));
    gl.uniform3fv(U.uSssSun, pal('sssSun'));
    gl.uniform3fv(U.uSssMoonA, pal('sssMoonA'));
    gl.uniform3fv(U.uSssMoonB, pal('sssMoonB'));
    gl.uniform3fv(U.uFoam, pal('foam'));
    gl.uniform3fv(U.uSunGlit, pal('sunGlit'));
    gl.uniform3fv(U.uMoonGlit, pal('moonGlit'));
    gl.uniform3fv(U.uCloudTint, pal('cloudTint'));
    gl.uniform1i(U.uSteps, steps);
    gl.uniform1f(U.uYaw, Math.sin(t * 0.05) * 0.12);

    gl.drawArrays(gl.TRIANGLES, 0, 3);

    // 性能保护：连续低帧自动降档
    if (dt > 0) {
      fpsAccum += 1 / dt;
      frameCount++;
      if (frameCount >= 40) {
        var avg = fpsAccum / frameCount;
        frameCount = 0;
        fpsAccum = 0;
        if (avg < 20) {
          lowFpsWindows++;
          if (lowFpsWindows >= 2 && degradeLevel < 3) {
            degradeLevel++;
            if (degradeLevel === 2) steps = 16;
            lowFpsWindows = 0;
          }
        } else {
          lowFpsWindows = 0;
        }
      }
    }
  }

  // ---------------- External API ----------------

  function applyPreset(mode) {
    var p = PRESETS[mode];
    if (!p) return;
    state.targetTimeOfDay = p.tod;
    state.targetSeaState = p.sea;
  }

  window.addEventListener('message', function (e) {
    var d = e.data;
    if (d && d.type === 'oceanMode' && typeof d.mode === 'string') {
      applyPreset(d.mode);
    }
  });

  window.__ocean = {
    setMode: applyPreset,
    setSeaState: function (n) {
      state.targetSeaState = Math.min(2, Math.max(0, Number(n) || 0));
    },
    pause: function () { running = false; },
    resume: function () { running = true; lastRenderAt = 0; },
    cleanup: function () {
      running = false;
      cancelAnimationFrame(rafId);
      try {
        gl.deleteBuffer(buf);
        gl.deleteShader(vs);
        gl.deleteShader(fs);
        gl.deleteProgram(prog);
        var ext = gl.getExtension('WEBGL_lose_context');
        if (ext) ext.loseContext();
      } catch (e) { /* ignore */ }
    }
  };

  resize();
  rafId = requestAnimationFrame(frame);
  notifyParent('oceanReady');
})();
