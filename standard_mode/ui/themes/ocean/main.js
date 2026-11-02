/*
 * Three.js TSL Ocean 动态壁纸
 * 用法：在支持 WebGPU 的现代浏览器中直接打开 index.html
 * 本文件使用 ES Modules + Three.js r160 + TSL 节点材质实现程序化海洋、天空与后期辉光
 */

import * as THREE from 'three';
import {
  uniform, tslFn, If, loop,
  positionLocal, positionWorld, cameraPosition, transformedNormalWorld,
  modelNormalMatrix, cameraViewMatrix,
  color, vec2, vec3, vec4, float,
  sin, cos, abs, floor, fract, pow, sqrt,
  length, dot, cross, normalize, min, max, clamp, saturate,
  mix, smoothstep, step, reflect, negate,
  add, sub, mul, div, assign, toVar,
  timerLocal, varying, hash,
  pass, gaussianBlur, luminance, toneMapping
} from 'three/tsl';
import WebGPURenderer from 'three/addons/renderers/webgpu/WebGPURenderer.js';
import WebGPU from 'three/addons/capabilities/WebGPU.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import PostProcessing from 'three/addons/renderers/common/PostProcessing.js';
import MeshPhysicalNodeMaterial from 'three/addons/nodes/materials/MeshPhysicalNodeMaterial.js';
import MeshBasicNodeMaterial from 'three/addons/nodes/materials/MeshBasicNodeMaterial.js';

const CONFIG = {
  oceanSize: 2400,
  oceanSegments: 192,
  dprMax: 1.5,
  cameraY: 7.5,
  cameraZ: 90
};

const state = {
  seaState: 1.0,
  timeOfDay: 12.0,
  drift: true
};

// UI elements
const loadingEl = document.getElementById('loading');
const errorEl = document.getElementById('error');
const errorTextEl = document.getElementById('error-text');
const fpsEl = document.getElementById('fps');
const seaInput = document.getElementById('sea');
const timeInput = document.getElementById('time');
const driftInput = document.getElementById('drift');
const valSeaEl = document.getElementById('val-sea');
const valTimeEl = document.getElementById('val-time');
const valDriftEl = document.getElementById('val-drift');
const uiPanelEl = document.getElementById('ui');

const urlParams = new URLSearchParams(location.search);
function clampLimit(v) {
  if (!isFinite(v)) return 60;
  return Math.min(144, Math.max(24, v));
}
const fpsLimit = clampLimit(parseInt(urlParams.get('fps') || '60', 10));

// 壁纸模式：UI 面板与 FPS 角标默认隐藏，仅 ?ui=1 时显示
if (urlParams.get('ui') === '1') {
  uiPanelEl.style.display = 'block';
  fpsEl.style.display = 'block';
}

function showError(msg) {
  errorTextEl.textContent = msg;
  loadingEl.classList.add('hidden');
  errorEl.classList.remove('hidden');
  try {
    if (window.parent && window.parent !== window) {
      window.parent.postMessage({ type: 'oceanError' }, '*');
    }
  } catch (e) { /* ignore */ }
}

function hideLoading() {
  loadingEl.classList.add('hidden');
}

// WebGPU check
if (!WebGPU.isAvailable()) {
  showError('您的浏览器或设备不支持 WebGPU，请使用最新版 Chrome / Edge / Safari 17+。');
  throw new Error('WebGPU not available');
}

// Uniforms
const uTime = uniform(0);
const uSeaState = uniform(state.seaState);
const uTimeOfDay = uniform(state.timeOfDay);
const uSunDir = uniform(new THREE.Vector3(0.3, 1, 0.2).normalize());

// --- TSL noise helpers ---

const noise2D = tslFn(([ p ]) => {
  const i = floor(p);
  const f = fract(p);
  const u = f.mul(f).mul(float(3).sub(f.mul(2)));

  const h00 = hash(i.add(vec2(0, 0))).x;
  const h10 = hash(i.add(vec2(1, 0))).x;
  const h01 = hash(i.add(vec2(0, 1))).x;
  const h11 = hash(i.add(vec2(1, 1))).x;

  const angle = float(6.28318);
  const g00 = vec2(cos(h00.mul(angle)), sin(h00.mul(angle)));
  const g10 = vec2(cos(h10.mul(angle)), sin(h10.mul(angle)));
  const g01 = vec2(cos(h01.mul(angle)), sin(h01.mul(angle)));
  const g11 = vec2(cos(h11.mul(angle)), sin(h11.mul(angle)));

  const n00 = g00.dot(f.sub(vec2(0, 0)));
  const n10 = g10.dot(f.sub(vec2(1, 0)));
  const n01 = g01.dot(f.sub(vec2(0, 1)));
  const n11 = g11.dot(f.sub(vec2(1, 1)));

  return mix(mix(n00, n10, u.x), mix(n01, n11, u.x), u.y);
});

const fbm2D = tslFn(([ p ]) => {
  const value = float(0).toVar();
  const amplitude = float(0.5).toVar();
  const frequency = float(1).toVar();

  loop(3, () => {
    value.addAssign(noise2D(p.mul(frequency)).mul(amplitude));
    amplitude.mulAssign(0.5);
    frequency.mulAssign(2);
  });

  return value;
});

// --- Analytical sky ---

const skyColor = tslFn(([ dir, sunDir, timeOfDay ]) => {
  const d = normalize(dir).toVar();
  const sd = normalize(sunDir).toVar();
  const sunDot = max(d.dot(sd), 0);
  const sunElev = sd.y;

  const dayZenith = vec3(0.0, 0.45, 1.0);
  const dayHorizon = vec3(0.65, 0.84, 1.0);
  const sunsetZenith = vec3(0.35, 0.23, 0.43);
  const sunsetHorizon = vec3(0.88, 0.26, 0.42);
  const nightZenith = vec3(0.006, 0.006, 0.035);
  const nightHorizon = vec3(0.03, 0.05, 0.12);

  const night = sub(1, smoothstep(-0.18, -0.06, sunElev));
  const day = smoothstep(0.06, 0.25, sunElev);
  const sunset = clamp(sub(1, night.add(day)), 0, 1);

  const zenith = nightZenith.mul(night).add(sunsetZenith.mul(sunset)).add(dayZenith.mul(day));
  const horizon = nightHorizon.mul(night).add(sunsetHorizon.mul(sunset)).add(dayHorizon.mul(day));

  const elevation = d.y;
  const skyT = smoothstep(-0.08, 0.7, elevation);
  const sky = mix(horizon, zenith, skyT);

  const sunDisc = smoothstep(0.9982, 0.9997, sunDot);
  const sunGlow = pow(sunDot, 65).mul(0.55);
  const sunColor = mix(sunsetHorizon, vec3(1.0, 0.98, 0.9), day);
  const sun = sunDisc.add(sunGlow).mul(sunColor);

  const cloudCoord = d.xz.div(max(abs(elevation), 0.04)).add(timeOfDay.mul(0.025));
  const cloudNoise = fbm2D(cloudCoord.mul(0.35)).mul(0.5).add(0.5);
  const cloudBand = sin(length(d.xz).mul(14).add(cloudNoise.mul(3))).mul(0.5).add(0.5);
  const cloudMask = smoothstep(0.44, 0.72, cloudBand)
    .mul(saturate(sub(1, abs(elevation).mul(2.2))))
    .mul(day.add(sunset.mul(0.35)));
  const cloudTint = mix(vec3(1.0, 0.6, 0.62), vec3(0.95, 0.98, 1.0), day);
  const clouds = cloudTint.mul(cloudMask);

  const starCell = floor(d.mul(260));
  const starHash = hash(starCell).x;
  const star = smoothstep(0.992, 0.998, starHash).mul(night);
  const stars = vec3(0.85, 0.92, 1.0).mul(star);

  const moonDir = normalize(negate(sd).add(vec3(0.18, 0.3, 0.12)));
  const moonDot = max(d.dot(moonDir), 0);
  const moonDisc = smoothstep(0.9993, 0.99975, moonDot);
  const moonHalo = pow(moonDot, 300).mul(0.4);
  const moon = moonDisc.mul(vec3(0.92, 0.95, 1.0)).add(moonHalo.mul(vec3(0.55, 0.62, 0.75))).mul(night);

  return sky.add(sun).add(clouds).add(stars).add(moon);
});

// --- Ocean material ---

const vOceanNormal = varying(vec3(), 'vOceanNormal');
const vOceanHeight = varying(float(), 'vOceanHeight');

const oceanPosition = tslFn(() => {
  const pos = positionLocal.toVar();
  const xz = pos.xz.toVar();
  const time = uTime;
  const sea = uSeaState;

  const tangent = vec3(1, 0, 0).toVar();
  const bitangent = vec3(0, 0, 1).toVar();
  const height = float(0).toVar();

  const addWave = (dirRaw, baseAmp, wl, speed, qRaw) => {
    const dir = normalize(dirRaw).toVar();
    const amp = float(baseAmp).mul(sea);
    const q = float(qRaw);
    const w = float(6.28318).div(float(wl));
    const phi = float(speed).mul(w).mul(time);
    const dotD = dir.dot(xz);
    const cosT = cos(dotD.mul(w).add(phi));
    const sinT = sin(dotD.mul(w).add(phi));

    height.addAssign(amp.mul(sinT));
    pos.x.addAssign(q.mul(amp).mul(dir.x).mul(cosT));
    pos.z.addAssign(q.mul(amp).mul(dir.y).mul(cosT));

    tangent.x.addAssign(negate(q.mul(dir.x).mul(dir.x).mul(w).mul(amp).mul(sinT)));
    tangent.y.addAssign(q.mul(dir.x).mul(w).mul(amp).mul(cosT));
    tangent.z.addAssign(negate(q.mul(dir.x).mul(dir.y).mul(w).mul(amp).mul(sinT)));

    bitangent.x.addAssign(negate(q.mul(dir.x).mul(dir.y).mul(w).mul(amp).mul(sinT)));
    bitangent.y.addAssign(q.mul(dir.y).mul(w).mul(amp).mul(cosT));
    bitangent.z.addAssign(negate(q.mul(dir.y).mul(dir.y).mul(w).mul(amp).mul(sinT)));
  };

  addWave(vec2(1.0, 0.3), 0.65, 140, 1.0, 0.28);
  addWave(vec2(0.6, 1.0), 0.48, 90, 1.15, 0.38);
  addWave(vec2(-0.8, 0.5), 0.36, 52, 0.9, 0.48);
  addWave(vec2(0.4, -0.9), 0.26, 28, 1.35, 0.58);
  addWave(vec2(-0.3, -0.7), 0.2, 14, 0.75, 0.68);

  // FBM surface detail (3 layers)
  const detailPos = xz.add(time.mul(0.28));
  const detailAmp = float(0.14).mul(sea);
  const detail = fbm2D(detailPos).mul(detailAmp);
  pos.y.addAssign(detail);
  height.addAssign(detail);

  // Perturb normal from detail using finite differences
  const eps = float(0.06);
  const dx = fbm2D(detailPos.add(vec2(eps, 0))).sub(fbm2D(detailPos.sub(vec2(eps, 0))));
  const dz = fbm2D(detailPos.add(vec2(0, eps))).sub(fbm2D(detailPos.sub(vec2(0, eps))));
  tangent.y.addAssign(dx.mul(detailAmp).div(eps.mul(2)));
  bitangent.y.addAssign(dz.mul(detailAmp).div(eps.mul(2)));

  const normal = normalize(cross(bitangent, tangent));

  vOceanNormal.assign(normal);
  vOceanHeight.assign(height);

  return pos;
});

const oceanNormal = tslFn(() => {
  const localNormal = normalize(vOceanNormal);
  const worldNormal = normalize(modelNormalMatrix.mul(localNormal));
  const viewNormal = normalize(cameraViewMatrix.transformDirection(worldNormal));
  return viewNormal;
});

const oceanColor = tslFn(() => {
  const normal = transformedNormalWorld.toVar();
  const viewDir = normalize(cameraPosition.sub(positionWorld));
  const reflectDir = reflect(negate(viewDir), normal);

  const skyReflect = skyColor(reflectDir, uSunDir, uTimeOfDay);

  const NdotV = max(dot(normal, viewDir), 0);
  const fresnel = pow(sub(1, NdotV), 3).mul(0.85).add(0.08);

  const sunElevW = uSunDir.y;
  const dayW = smoothstep(0.06, 0.25, sunElevW);
  const nightW = sub(1, smoothstep(-0.18, -0.06, sunElevW));
  const sunsetW = clamp(sub(1, dayW.add(nightW)), 0, 1);

  const deepColor = vec3(0.0, 0.06, 0.15);
  const shallowColor = vec3(0.0, 0.34, 0.45);
  const heightFactor = saturate(vOceanHeight.mul(0.55).add(0.5));
  const waterDay = mix(deepColor, shallowColor, heightFactor);
  const waterNight = mix(vec3(0.102, 0.051, 0.031), vec3(0.23, 0.105, 0.05), heightFactor);
  const waterBase = mix(waterDay, waterNight, nightW.mul(0.9));

  const sunDotN = max(dot(normal, uSunDir), 0);
  const crestH = saturate(vOceanHeight);
  const sssDay = pow(sunDotN, 2).mul(crestH).mul(vec3(0.38, 0.58, 0.48));
  const sssSunset = pow(sunDotN, 2).mul(crestH).mul(vec3(0.85, 0.35, 0.42));
  const moonDirW = normalize(negate(normalize(uSunDir)).add(vec3(0.18, 0.3, 0.12)));
  const moonDotN = max(dot(normal, moonDirW), 0);
  const nightCrest = mix(vec3(0.541, 0.29, 0.125), vec3(0.761, 0.4, 0.122), saturate(vOceanHeight.mul(0.5).add(0.5)));
  const sssNight = pow(moonDotN, 1.6).mul(crestH).mul(nightCrest).mul(1.2);
  const sss = sssDay.mul(dayW).add(sssSunset.mul(sunsetW)).add(sssNight.mul(nightW));

  const foamTint = vec3(0.94, 0.98, 1.0).mul(dayW)
    .add(vec3(1.0, 0.62, 0.6).mul(sunsetW))
    .add(vec3(0.5, 0.3, 0.15).mul(nightW));
  const foam = smoothstep(0.58, 0.88, vOceanHeight).mul(foamTint);

  const litWater = waterBase.add(sss).add(foam);
  const colorWithReflection = mix(litWater, skyReflect, fresnel);

  const horizonFog = pow(sub(1, saturate(viewDir.y)), 3.5).mul(0.55);
  const fogColor = skyColor(vec3(0, 1, 0), uSunDir, uTimeOfDay);
  const finalColor = mix(colorWithReflection, fogColor, horizonFog);

  return vec4(finalColor, 1.0);
});

const oceanGlitter = tslFn(() => {
  const normal = transformedNormalWorld;
  const viewDir = normalize(cameraPosition.sub(positionWorld));
  const reflectDir = reflect(negate(viewDir), normal);
  const sunElevG = uSunDir.y;
  const dayG = smoothstep(0.06, 0.25, sunElevG);
  const nightG = sub(1, smoothstep(-0.18, -0.06, sunElevG));

  const sunReflect = max(dot(reflectDir, uSunDir), 0);
  const sunGlit = pow(sunReflect, 160).mul(1.8).mul(smoothstep(-0.1, 0.4, sunElevG));
  const sunGlitColor = mix(vec3(1.0, 0.56, 0.42), vec3(1.0, 0.96, 0.85), dayG);

  const moonDirG = normalize(negate(normalize(uSunDir)).add(vec3(0.18, 0.3, 0.12)));
  const moonReflect = max(dot(reflectDir, moonDirG), 0);
  const moonGlit = pow(moonReflect, 220).mul(1.3).mul(nightG);

  const glit = sunGlitColor.mul(sunGlit).add(vec3(0.81, 0.85, 0.91).mul(moonGlit));
  return vec4(glit, 1.0);
});

// --- Scene setup ---

const scene = new THREE.Scene();

const camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 0.1, 5000);
camera.position.set(0, CONFIG.cameraY, CONFIG.cameraZ);

const renderer = new WebGPURenderer({ antialias: true, alpha: false });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, CONFIG.dprMax));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.toneMapping = THREE.NoToneMapping;
renderer.setClearColor(0x000510, 1);
document.getElementById('canvas-container').appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.06;
controls.maxPolarAngle = Math.PI / 2 - 0.02;
controls.minDistance = 10;
controls.maxDistance = 400;
controls.target.set(0, 0, 0);
controls.autoRotate = state.drift;
controls.autoRotateSpeed = 0.25;

// Sun light follows analytical sun
const sunLight = new THREE.DirectionalLight(0xfffff0, 2.2);
scene.add(sunLight);
const ambientLight = new THREE.AmbientLight(0x405070, 0.6);
scene.add(ambientLight);

// Sky dome
const skyGeo = new THREE.SphereGeometry(4000, 64, 64);
const skyMat = new MeshBasicNodeMaterial({ side: THREE.BackSide });
skyMat.colorNode = skyColor(positionWorld, uSunDir, uTimeOfDay);
const sky = new THREE.Mesh(skyGeo, skyMat);
scene.add(sky);

// Ocean mesh
const oceanGeo = new THREE.PlaneGeometry(CONFIG.oceanSize, CONFIG.oceanSize, CONFIG.oceanSegments, CONFIG.oceanSegments).rotateX(-Math.PI / 2);
const oceanMat = new MeshPhysicalNodeMaterial({
  roughness: 0.045,
  metalness: 0.05,
  ior: 1.33,
  reflectivity: 0.6,
  clearcoat: 0.2,
  clearcoatRoughness: 0.05,
  lights: false,
  toneMapped: false
});
oceanMat.positionNode = oceanPosition();
oceanMat.normalNode = oceanNormal();
oceanMat.colorNode = oceanColor();
oceanMat.emissiveNode = oceanGlitter();

const ocean = new THREE.Mesh(oceanGeo, oceanMat);
scene.add(ocean);

// Post-processing: TSL bloom built with gaussianBlur + threshold mask, ACES tone mapping
const scenePass = pass(scene, camera);
const sceneColor = scenePass.getTextureNode();
const blurred = gaussianBlur(sceneColor, 5);
const bloomMask = smoothstep(0.5, 0.78, luminance(blurred.rgb));
const uBloomStrength = uniform(0.75);
const bloom = blurred.rgb.mul(bloomMask).mul(uBloomStrength);
const colorWithBloom = sceneColor.rgb.add(bloom);
const toneMapped = toneMapping(THREE.ACESFilmicToneMapping, float(0.95), colorWithBloom);
const postNode = vec4(toneMapped, sceneColor.a);

const postProcessing = new PostProcessing(renderer, postNode);

// --- Sun / time update ---

function updateSun() {
  const t = state.timeOfDay;
  const angle = (t - 6) / 12 * Math.PI; // 6:00 sunrise, 12:00 noon, 18:00 sunset
  const y = Math.sin(angle);
  const x = Math.cos(angle);
  const z = 0.25;
  const dir = new THREE.Vector3(x, y, z).normalize();
  uSunDir.value.copy(dir);
  sunLight.position.copy(dir).multiplyScalar(1000);

  const sunElev = y;
  if (sunElev > 0.15) {
    sunLight.color.setHex(0xfffff0);
    sunLight.intensity = 2.0;
    ambientLight.color.setHex(0x506070);
    ambientLight.intensity = 0.6;
  } else if (sunElev > -0.1) {
    sunLight.color.setHex(0xff9e7a);
    sunLight.intensity = 1.4;
    ambientLight.color.setHex(0x604030);
    ambientLight.intensity = 0.5;
  } else {
    sunLight.color.setHex(0xa8b8d8);
    sunLight.intensity = 0.5;
    ambientLight.color.setHex(0x101528);
    ambientLight.intensity = 0.25;
  }
}

// --- UI bindings ---

function formatTime(v) {
  const h = Math.floor(v);
  const m = Math.floor((v - h) * 60);
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`;
}

function updateUI() {
  valSeaEl.textContent = state.seaState.toFixed(2);
  valTimeEl.textContent = formatTime(state.timeOfDay);
  valDriftEl.textContent = state.drift ? 'ON' : 'OFF';

  seaInput.value = state.seaState;
  timeInput.value = state.timeOfDay;
  driftInput.value = state.drift ? 1 : 0;
}

const ac = new AbortController();
const listenOpt = { signal: ac.signal };

function clampNum(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }

function setSeaStateValue(n) {
  state.seaState = clampNum(n, 0, 2);
  uSeaState.value = state.seaState;
  valSeaEl.textContent = state.seaState.toFixed(2);
}

function applyPreset(preset) {
  if (preset === 'day') {
    state.seaState = 1.0;
    state.timeOfDay = 12.0;
  } else if (preset === 'sunset') {
    state.seaState = 1.2;
    state.timeOfDay = 17.8;
  } else if (preset === 'night') {
    state.seaState = 0.6;
    state.timeOfDay = 2.0;
  } else {
    return;
  }
  uSeaState.value = state.seaState;
  uTimeOfDay.value = state.timeOfDay;
  updateSun();
  updateUI();
}

seaInput.addEventListener('input', (e) => {
  setSeaStateValue(parseFloat(e.target.value));
}, listenOpt);

timeInput.addEventListener('input', (e) => {
  state.timeOfDay = parseFloat(e.target.value);
  uTimeOfDay.value = state.timeOfDay;
  valTimeEl.textContent = formatTime(state.timeOfDay);
  updateSun();
}, listenOpt);

driftInput.addEventListener('input', (e) => {
  state.drift = parseInt(e.target.value, 10) === 1;
  controls.autoRotate = state.drift;
  valDriftEl.textContent = state.drift ? 'ON' : 'OFF';
}, listenOpt);

document.querySelectorAll('[data-preset]').forEach((btn) => {
  btn.addEventListener('click', () => applyPreset(btn.dataset.preset), listenOpt);
});

// 父页面（lemon_code 右侧栏）三态按钮桥接
window.addEventListener('message', (e) => {
  const d = e.data;
  if (d && d.type === 'oceanMode' && typeof d.mode === 'string') {
    applyPreset(d.mode);
  }
}, listenOpt);

// --- Resize & visibility ---

let currentDpr = Math.min(window.devicePixelRatio, CONFIG.dprMax);

function onResize() {
  const width = window.innerWidth;
  const height = window.innerHeight;
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  renderer.setSize(width, height);
  currentDpr = degradeLevel >= 1 ? 1 : Math.min(window.devicePixelRatio, CONFIG.dprMax);
  renderer.setPixelRatio(currentDpr);
}
window.addEventListener('resize', onResize, listenOpt);

let isVisible = true;
let paused = false;
document.addEventListener('visibilitychange', () => {
  isVisible = document.visibilityState === 'visible';
}, listenOpt);

// --- Performance guard ---

let lastFrameTime = performance.now();
let frameCount = 0;
let fpsAccumulator = 0;
let fpsLowFrames = 0;
let degradeLevel = 0; // 0 无 | 1 降DPR | 2 降网格 | 3 关Bloom

function applyDegrade(level) {
  if (level === 1) {
    currentDpr = 1;
    renderer.setPixelRatio(currentDpr);
  } else if (level === 2) {
    const old = ocean.geometry;
    ocean.geometry = new THREE.PlaneGeometry(CONFIG.oceanSize, CONFIG.oceanSize, 128, 128).rotateX(-Math.PI / 2);
    old.dispose();
  } else if (level >= 3) {
    uBloomStrength.value = 0;
  }
}

function updateFPS() {
  const now = performance.now();
  const dt = (now - lastFrameTime) / 1000;
  lastFrameTime = now;

  if (dt > 0) {
    const fps = 1 / dt;
    fpsAccumulator += fps;
    frameCount++;

    if (frameCount % 30 === 0) {
      const avg = fpsAccumulator / 30;
      fpsEl.textContent = `FPS: ${Math.round(avg)}`;
      fpsAccumulator = 0;

      if (avg < 20) {
        fpsLowFrames++;
        if (fpsLowFrames > 3 && degradeLevel < 3) {
          degradeLevel++;
          applyDegrade(degradeLevel);
          fpsLowFrames = 0;
          fpsEl.textContent = 'FPS: 优化 L' + degradeLevel;
        }
      } else {
        fpsLowFrames = Math.max(0, fpsLowFrames - 1);
      }
    }
  }
}

// --- Animation ---

const clock = new THREE.Clock();

let rafId = 0;
let lastRenderAt = 0;

function animate() {
  rafId = requestAnimationFrame(animate);

  if (!isVisible || paused) return;

  const nowMs = performance.now();
  if (nowMs - lastRenderAt < 1000 / fpsLimit - 0.5) return;
  lastRenderAt = nowMs;

  const dt = clock.getDelta();
  uTime.value = clock.getElapsedTime();

  controls.update();
  updateFPS();

  try {
    postProcessing.render();
  } catch (err) {
    console.error(err);
    showError('渲染过程中发生错误：' + (err.message || String(err)));
  }
}

// --- External wallpaper API (供 lemon_code 内置壁纸系统调用) ---

function pause() { paused = true; }
function resume() { paused = false; lastRenderAt = 0; }

function cleanup() {
  try { ac.abort(); } catch (e) { /* ignore */ }
  cancelAnimationFrame(rafId);
  try { controls.dispose(); } catch (e) { /* ignore */ }
  scene.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    if (o.material) {
      const mats = Array.isArray(o.material) ? o.material : [o.material];
      mats.forEach((m) => { if (m && m.dispose) m.dispose(); });
    }
  });
  try { if (postProcessing && postProcessing.dispose) postProcessing.dispose(); } catch (e) { /* ignore */ }
  try { renderer.dispose(); } catch (e) { /* ignore */ }
  const container = document.getElementById('canvas-container');
  if (container) container.innerHTML = '';
}

window.__ocean = {
  setMode: applyPreset,
  setSeaState: setSeaStateValue,
  pause,
  resume,
  cleanup
};

// --- Init ---

async function init() {
  try {
    await renderer.init();
  } catch (err) {
    showError('WebGPU 渲染器初始化失败：' + (err.message || String(err)));
    return;
  }

  updateSun();
  updateUI();
  onResize();
  hideLoading();
  animate();
  try {
    if (window.parent && window.parent !== window) {
      window.parent.postMessage({ type: 'oceanReady' }, '*');
    }
  } catch (e) { /* ignore */ }
}

init();
