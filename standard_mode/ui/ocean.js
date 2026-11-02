// ============================================================
// Lemon Ocean — 电影级海洋壁纸 v3
// Gerstner 32 层涌浪 + Jacobian 白沫 + FBM 微表面 + 环境贴图 + Bloom
// 参考 Kimi Open Sea: Realtime WebGPU Ocean
// ============================================================

const canvas = document.getElementById('canvas');
const loadingEl = document.getElementById('loading');
const errorEl = document.getElementById('error');
const flashEl = document.getElementById('flash');

let renderer, scene, camera;
let oceanMesh, oceanMaterial, oceanGeometry;
let sparkleSystem, sparkleGeo, sparkleMat;
let sunLight, ambientLight;
let sunMesh, sunGlow, sunGlowOuter, sunGlowHalo;
let starsSystem, starsMat;
let skyMesh, skyMaterial;
let lighthouseGroup, lighthouseBeam, lighthouseBulb, lighthouseSpot;
let lighthouseBaseOpacity = 0.22;
let lighthouseBaseIntensity = 0;
let time = 0;
let isVisible = true;

// 后处理对象
let postScene, postCamera, postQuad;
let sceneRenderTarget, bloomExtractTarget, blurTargetH, blurTargetV;
let bloomExtractMat, bloomBlurHMat, bloomBlurVMat, combineMat;
let envCubeRenderTarget, envCubeCamera;
let errorHideTimer = null;

// ============================================================
// 三模式配置（颜色针对 HDR + Bloom 重新校准）
// ============================================================
const MODES = {
  day: {
    name: 'day',
    sunDir: new THREE.Vector3(0.32, 0.72, -0.60).normalize(),
    sunColor: new THREE.Color(1.22, 1.18, 1.05),
    sunGlowColor: new THREE.Color(1.0, 0.96, 0.78),
    sunIntensity: 3.4,
    ambientColor: new THREE.Color(0.55, 0.82, 1.0),
    ambientIntensity: 0.52,
    deepColor: new THREE.Color(0.0, 0.32, 0.55),
    shallowColor: new THREE.Color(0.06, 0.86, 0.98),
    foamColor: new THREE.Color(0.96, 1.0, 1.0),
    skyTop: new THREE.Color(0.16, 0.58, 0.92),
    skyMid: new THREE.Color(0.42, 0.80, 0.98),
    skyBottom: new THREE.Color(0.72, 0.92, 1.0),
    horizonColor: new THREE.Color(0.80, 0.94, 1.0),
    fogNear: 200,
    fogFar: 460,
    sparkleColor: new THREE.Color(1.0, 1.0, 0.96),
    waveAmpScale: 1.30,
    roughness: 0.032,
    sunDiskSize: 3.2,
    starOpacity: 0.0,
    sunGlintStrength: 1.4,
    bloomStrength: 0.48,
    bloomThreshold: 1.10
  },
  sunset: {
    name: 'sunset',
    sunDir: new THREE.Vector3(0.48, 0.05, -0.87).normalize(),
    sunColor: new THREE.Color(1.0, 0.62, 0.32),
    sunGlowColor: new THREE.Color(1.0, 0.40, 0.26),
    sunIntensity: 2.6,
    ambientColor: new THREE.Color(0.85, 0.48, 0.40),
    ambientIntensity: 0.38,
    deepColor: new THREE.Color(0.02, 0.15, 0.35),
    shallowColor: new THREE.Color(0.0, 0.58, 0.75),
    foamColor: new THREE.Color(1.0, 0.68, 0.52),
    skyTop: new THREE.Color(0.72, 0.55, 0.72),
    skyMid: new THREE.Color(0.95, 0.52, 0.38),
    skyBottom: new THREE.Color(1.0, 0.45, 0.28),
    horizonColor: new THREE.Color(1.0, 0.48, 0.32),
    fogNear: 140,
    fogFar: 360,
    sparkleColor: new THREE.Color(1.0, 0.55, 0.32),
    waveAmpScale: 1.35,
    roughness: 0.040,
    sunDiskSize: 6.0,
    starOpacity: 0.12,
    sunGlintStrength: 1.5,
    bloomStrength: 0.72,
    bloomThreshold: 0.88
  },
  night: {
    name: 'night',
    sunDir: new THREE.Vector3(-0.22, 0.72, -0.66).normalize(),
    sunColor: new THREE.Color(0.55, 0.65, 0.85),
    sunGlowColor: new THREE.Color(0.18, 0.28, 0.45),
    sunIntensity: 0.65,
    ambientColor: new THREE.Color(0.03, 0.05, 0.10),
    ambientIntensity: 0.045,
    deepColor: new THREE.Color(0.003, 0.008, 0.018),
    shallowColor: new THREE.Color(0.010, 0.026, 0.048),
    foamColor: new THREE.Color(0.035, 0.065, 0.11),
    skyTop: new THREE.Color(0.002, 0.004, 0.010),
    skyMid: new THREE.Color(0.004, 0.008, 0.016),
    skyBottom: new THREE.Color(0.006, 0.014, 0.026),
    horizonColor: new THREE.Color(0.004, 0.010, 0.020),
    fogNear: 45,
    fogFar: 160,
    sparkleColor: new THREE.Color(0.55, 0.70, 1.0),
    waveAmpScale: 0.55,
    roughness: 0.085,
    sunDiskSize: 1.6,
    starOpacity: 1.0,
    sunGlintStrength: 0.45,
    bloomStrength: 0.18,
    bloomThreshold: 1.7
  }
};

const urlParams = new URLSearchParams(window.location.search);
let currentModeKey = urlParams.get('mode') || 'day';
if (!MODES[currentModeKey]) currentModeKey = 'day';
let mode = MODES[currentModeKey];

const OCEAN_CONFIG = {
  segments: 360,
  size: 2600,
  sparkleCount: 0,
  sparkleSize: 5.0,
  starCount: 18000,
  bloomDownScale: 0.5,
  bloomIterations: 3
};

// ============================================================
// 32 层 Gerstner 波生成（5 个倍频程，每层方向/相位差异化）
// ============================================================
function seededRandom(seed) {
  let s = seed % 2147483647;
  if (s <= 0) s += 2147483646;
  return function () {
    s = (s * 16807) % 2147483647;
    return (s - 1) / 2147483646;
  };
}

function generateWaves() {
  const rng = seededRandom(20240729);
  const waves = [];
  const dominantAngle = Math.PI * 0.12;
  const wavesPerOctave = [6, 7, 8, 6, 5];
  const baseLen = 280.0;

  for (let o = 0; o < wavesPerOctave.length; o++) {
    const waveLen = baseLen / Math.pow(2.0, o);
    const ampBase = 1.05 / Math.pow(2.0, o * 0.55);
    const spread = 0.22 + o * 0.18;
    const n = wavesPerOctave[o];

    for (let j = 0; j < n; j++) {
      const baseAngle = dominantAngle + (j / (n - 1) - 0.5) * spread * 0.6;
      const angle = baseAngle + (rng() - 0.5) * spread;
      const dir = new THREE.Vector2(Math.cos(angle), Math.sin(angle)).normalize();
      const amp = ampBase * (0.55 + 0.85 * rng()) * (1.0 + o * 0.08);
      const speed = (0.30 + 0.22 * rng() + o * 0.06) * 1.45;
      const q = Math.min(0.80, 0.14 + 0.55 * (1.0 - o / wavesPerOctave.length));
      waves.push({ dir, amp, waveLen, speed, q });
    }
  }
  return waves;
}

const BASE_WAVES = generateWaves();
const WAVE_COUNT = BASE_WAVES.length;

init();

// ============================================================
// 初始化
// ============================================================
function init() {
  try {
    const testCanvas = document.createElement('canvas');
    const gl = testCanvas.getContext('webgl2') || testCanvas.getContext('webgl') || testCanvas.getContext('experimental-webgl');
    if (!gl) {
      throw new Error('当前浏览器/环境不支持 WebGL，无法渲染 3D 海洋。');
    }

    let w = window.innerWidth || canvas.clientWidth || 1;
    let h = window.innerHeight || canvas.clientHeight || 1;
    if (w < 2 || h < 2) { w = 1920; h = 1080; }

    const dpr = Math.min(window.devicePixelRatio || 1, 1.35);
    renderer = new THREE.WebGLRenderer({ canvas, antialias: false, alpha: false, powerPreference: 'high-performance' });
    renderer.setPixelRatio(dpr);
    renderer.setSize(w, h);
    renderer.shadowMap.enabled = false;
    renderer.toneMapping = THREE.NoToneMapping;
    if (renderer.outputColorSpace !== undefined && THREE.LinearSRGBColorSpace !== undefined) {
      renderer.outputColorSpace = THREE.LinearSRGBColorSpace;
    } else if (renderer.outputEncoding !== undefined && THREE.LinearEncoding !== undefined) {
      renderer.outputEncoding = THREE.LinearEncoding;
    }

    scene = new THREE.Scene();

    camera = new THREE.PerspectiveCamera(52, w / h, 0.1, 5000);
    camera.position.set(0, 6.8, 88);
    camera.lookAt(0, 0.35, 0);

    createSky();
    createStars();
    createSun();
    createLighthouse();
    createOcean();
    createSparkles();
    setupLighting();
    createEnvironmentMap();
    if (oceanMaterial && envCubeRenderTarget) {
      oceanMaterial.uniforms.uEnvMap.value = envCubeRenderTarget.texture;
    }
    renderer.setClearColor(mode.horizonColor, 1.0);
    initPostProcessing();
    applyModeToScene();

    window.addEventListener('resize', onWindowResize);
    document.addEventListener('visibilitychange', onVisibilityChange);
    window.addEventListener('message', onMessage);

    setTimeout(() => {
      if (renderer) {
        const cw = window.innerWidth || canvas.clientWidth || 1;
        const ch = window.innerHeight || canvas.clientHeight || 1;
        if (cw > 1 && ch > 1) {
          renderer.setSize(cw, ch);
          camera.aspect = cw / ch;
          camera.updateProjectionMatrix();
          resizePostProcessing(cw, ch);
        }
      }
    }, 100);

    loadingEl.style.opacity = '0';
    setTimeout(() => loadingEl.remove(), 700);

    animate();
  } catch (e) {
    console.error('[Ocean Init Error]', e);
    showError('初始化失败: ' + e.message);
  }
}

// ============================================================
// 程序化天空穹顶
// ============================================================
function createSky() {
  const vertexShader = `
    varying vec3 vWorldDir;
    void main() {
      vec4 wp = modelMatrix * vec4(position, 1.0);
      vWorldDir = normalize(wp.xyz);
      gl_Position = projectionMatrix * viewMatrix * wp;
    }
  `;

  const fragmentShader = `
    uniform vec3 topColor;
    uniform vec3 midColor;
    uniform vec3 bottomColor;
    uniform vec3 sunDir;
    uniform vec3 sunColor;
    uniform vec3 sunGlowColor;
    uniform float sunDiskSize;
    varying vec3 vWorldDir;

    void main() {
      float h = vWorldDir.y;
      vec3 col;

      // 四层渐变，让天空过渡更柔和
      float t1 = smoothstep(-0.18, 0.08, h);
      float t2 = smoothstep(0.08, 0.38, h);
      float t3 = smoothstep(0.38, 0.78, h);
      vec3 lowColor = mix(bottomColor, bottomColor * 0.82, smoothstep(-0.06, -0.22, h));
      col = mix(lowColor, bottomColor, t1);
      col = mix(col, midColor, t2);
      col = mix(col, topColor, t3);

      // 地平线雾气
      col = mix(col, lowColor, smoothstep(0.08, -0.14, h) * 0.70);

      // 太阳/月亮光晕
      float sunDot = max(0.0, dot(vWorldDir, normalize(sunDir)));
      float glowWide = pow(sunDot, 2.0) * 0.22;
      float glowMid = pow(sunDot, 5.5) * 0.28;
      float glowTight = pow(sunDot, 14.0) * 0.38;
      col += sunGlowColor * (glowWide + glowMid + glowTight);

      float sunDisk = smoothstep(0.998 - sunDiskSize * 0.0007, 0.999, sunDot);
      col = mix(col, sunColor, sunDisk * 0.94);

      gl_FragColor = vec4(col, 1.0);
    }
  `;

  const skyGeo = new THREE.SphereGeometry(4000, 72, 72);
  skyMaterial = new THREE.ShaderMaterial({
    vertexShader,
    fragmentShader,
    uniforms: {
      topColor: { value: mode.skyTop },
      midColor: { value: mode.skyMid },
      bottomColor: { value: mode.skyBottom },
      sunDir: { value: mode.sunDir },
      sunColor: { value: mode.sunColor },
      sunGlowColor: { value: mode.sunGlowColor },
      sunDiskSize: { value: mode.sunDiskSize }
    },
    side: THREE.BackSide,
    depthWrite: false
  });

  skyMesh = new THREE.Mesh(skyGeo, skyMaterial);
  scene.add(skyMesh);
}

// ============================================================
// 星空（银河分布）
// ============================================================
function createStars() {
  const count = OCEAN_CONFIG.starCount;
  const positions = new Float32Array(count * 3);
  const colors = new Float32Array(count * 3);
  const sizes = new Float32Array(count);
  const twinkle = new Float32Array(count);

  for (let i = 0; i < count; i++) {
    let theta = 0;
    let phi = Math.PI * 0.5;
    let density = 0;
    let accepted = false;
    let attempts = 0;

    while (!accepted && attempts < 30) {
      theta = Math.random() * Math.PI * 2;
      const u = Math.pow(Math.random(), 1.55);
      phi = Math.acos(1.0 - 2.0 * u * 0.5);

      const lat = phi - Math.PI * 0.5;
      const lon = theta;
      const core = Math.exp(-lat * lat / (2.0 * 0.06 * 0.06));
      const armPhase = lon * 2.1 + Math.log(Math.abs(lat) + 0.07) * 1.35;
      const arms = 0.55 + 0.45 * Math.sin(armPhase);
      const bulge = Math.exp(-(lat * lat + lon * lon * 0.12) / 0.012) * 0.55;
      density = Math.min(1.0, core * arms + bulge);

      if (Math.random() < density * 0.42 + 0.05) accepted = true;
      attempts++;
    }

    const r = 1500 + Math.random() * 900;
    positions[i*3] = r * Math.sin(phi) * Math.cos(theta);
    positions[i*3+1] = r * Math.cos(phi);
    positions[i*3+2] = r * Math.sin(phi) * Math.sin(theta);

    const c = new THREE.Color();
    const rn = Math.random();
    if (density > 0.75) {
      if (rn < 0.45) c.setHSL(0.10, 0.25 + Math.random() * 0.25, 0.72 + Math.random() * 0.22);
      else if (rn < 0.75) c.setHSL(0.78 + Math.random() * 0.08, 0.30 + Math.random() * 0.25, 0.70 + Math.random() * 0.22);
      else c.setHSL(0.00, 0.35 + Math.random() * 0.20, 0.68 + Math.random() * 0.20);
    } else if (density > 0.35) {
      if (rn < 0.55) c.setHSL(0.58 + Math.random() * 0.10, 0.25 + Math.random() * 0.25, 0.68 + Math.random() * 0.25);
      else if (rn < 0.85) c.setHSL(0.65 + Math.random() * 0.08, 0.30 + Math.random() * 0.20, 0.65 + Math.random() * 0.25);
      else c.setHSL(0.08, 0.25 + Math.random() * 0.15, 0.70 + Math.random() * 0.20);
    } else {
      c.setHSL(0.60 + Math.random() * 0.08, 0.10 + Math.random() * 0.15, 0.70 + Math.random() * 0.20);
    }

    colors[i*3] = c.r;
    colors[i*3+1] = c.g;
    colors[i*3+2] = c.b;
    sizes[i] = 0.35 + density * 4.2 + Math.random() * 1.1;
    twinkle[i] = Math.random() * Math.PI * 2;
  }

  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  geo.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1));
  geo.setAttribute('aTwinkle', new THREE.BufferAttribute(twinkle, 1));

  const vertexShader = `
    attribute vec3 color;
    attribute float aSize;
    attribute float aTwinkle;
    uniform float uTime;
    uniform float uPixelRatio;
    uniform float uStarOpacity;
    varying vec3 vColor;
    varying float vAlpha;
    void main() {
      vColor = color;
      float tw = 0.55 + 0.45 * sin(uTime * 1.1 + aTwinkle * 5.0);
      vAlpha = tw * uStarOpacity;
      vec4 mv = modelViewMatrix * vec4(position, 1.0);
      gl_PointSize = aSize * uPixelRatio * (900.0 / -mv.z);
      gl_Position = projectionMatrix * mv;
    }
  `;

  const fragmentShader = `
    uniform float uStarOpacity;
    varying vec3 vColor;
    varying float vAlpha;
    void main() {
      vec2 uv = gl_PointCoord - 0.5;
      float d = length(uv);
      if (d > 0.5) discard;
      float core = 1.0 - smoothstep(0.0, 0.10, d);
      float glow = 1.0 - smoothstep(0.0, 0.5, d);
      float crossGlow = max(0.0, 1.0 - abs(uv.x) * 7.0) * max(0.0, 1.0 - abs(uv.y) * 7.0);
      float star = core * 1.8 + glow * 0.7 + crossGlow * 0.5;
      float nightBoost = 1.0 + uStarOpacity * 0.9;
      gl_FragColor = vec4(vColor * nightBoost * (1.0 + core * 1.5), vAlpha * star);
    }
  `;

  starsMat = new THREE.ShaderMaterial({
    vertexShader,
    fragmentShader,
    uniforms: {
      uTime: { value: 0 },
      uPixelRatio: { value: renderer.getPixelRatio() },
      uStarOpacity: { value: mode.starOpacity }
    },
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending
  });

  starsSystem = new THREE.Points(geo, starsMat);
  scene.add(starsSystem);
}

// ============================================================
// 太阳 / 月亮
// ============================================================
function createSun() {
  const sunPos = mode.sunDir.clone().multiplyScalar(1200);

  const sunGeo = new THREE.SphereGeometry(mode.sunDiskSize * 0.9, 32, 32);
  const sunMat = new THREE.MeshBasicMaterial({ color: mode.sunColor });
  sunMesh = new THREE.Mesh(sunGeo, sunMat);
  sunMesh.position.copy(sunPos);
  scene.add(sunMesh);

  const glowGeo = new THREE.SphereGeometry(mode.sunDiskSize * 2.4, 32, 32);
  const glowMat = new THREE.MeshBasicMaterial({
    color: mode.sunGlowColor,
    transparent: true,
    opacity: 0.26,
    side: THREE.BackSide,
    depthWrite: false,
    blending: THREE.AdditiveBlending
  });
  sunGlow = new THREE.Mesh(glowGeo, glowMat);
  sunGlow.position.copy(sunPos);
  scene.add(sunGlow);

  const glow2Geo = new THREE.SphereGeometry(mode.sunDiskSize * 5.5, 32, 32);
  const glow2Mat = new THREE.MeshBasicMaterial({
    color: mode.sunGlowColor,
    transparent: true,
    opacity: 0.12,
    side: THREE.BackSide,
    depthWrite: false,
    blending: THREE.AdditiveBlending
  });
  sunGlowOuter = new THREE.Mesh(glow2Geo, glow2Mat);
  sunGlowOuter.position.copy(sunPos);
  scene.add(sunGlowOuter);

  const haloGeo = new THREE.SphereGeometry(mode.sunDiskSize * 14.0, 32, 32);
  const haloMat = new THREE.MeshBasicMaterial({
    color: mode.sunGlowColor,
    transparent: true,
    opacity: 0.04,
    side: THREE.BackSide,
    depthWrite: false,
    blending: THREE.AdditiveBlending
  });
  sunGlowHalo = new THREE.Mesh(haloGeo, haloMat);
  sunGlowHalo.position.copy(sunPos);
  scene.add(sunGlowHalo);
}

// ============================================================
// 环境贴图（捕获天空穹顶）
// ============================================================
function createEnvironmentMap() {
  envCubeRenderTarget = new THREE.WebGLCubeRenderTarget(256, {
    format: THREE.RGBAFormat,
    type: THREE.HalfFloatType,
    generateMipmaps: true,
    minFilter: THREE.LinearMipmapLinearFilter,
    magFilter: THREE.LinearFilter
  });
  envCubeCamera = new THREE.CubeCamera(0.1, 5000, envCubeRenderTarget);
  scene.add(envCubeCamera);
  updateEnvironmentMap();
}

function updateEnvironmentMap() {
  if (!envCubeCamera || !oceanMesh) return;
  const oceanVisible = oceanMesh.visible;
  const sparkleVisible = sparkleSystem ? sparkleSystem.visible : false;
  oceanMesh.visible = false;
  if (sparkleSystem) sparkleSystem.visible = false;
  envCubeCamera.update(renderer, scene);
  oceanMesh.visible = oceanVisible;
  if (sparkleSystem) sparkleSystem.visible = sparkleVisible;
}

// ============================================================
// 远处灯塔 + 旋转探照灯
// ============================================================
function createLighthouse() {
  try {
    lighthouseGroup = new THREE.Group();
    lighthouseGroup.name = 'lighthouse';
    // 放在左侧远处地平线附近，放大 2.2 倍，更醒目
    lighthouseGroup.position.set(-620, -1.2, -880);
    lighthouseGroup.scale.set(2.2, 2.2, 2.2);

    // 塔身（白色主体，红白混搭）
    const towerGeo = new THREE.CylinderGeometry(3.2, 7.0, 40, 18);
    const towerMat = new THREE.MeshBasicMaterial({ color: 0xf5f5f5 });
  const tower = new THREE.Mesh(towerGeo, towerMat);
  tower.position.y = 20;
  tower.castShadow = false;
  lighthouseGroup.add(tower);

  // 红白交替条纹装饰
  for (let i = 0; i < 5; i++) {
    const stripeGeo = new THREE.CylinderGeometry(3.38 + i * 0.06, 3.38 + i * 0.06, 4.0, 18, 1, true);
    const isRed = i % 2 === 0;
    const stripeMat = new THREE.MeshBasicMaterial({
      color: isRed ? 0xd62828 : 0xf8f8f8,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.92
    });
    const stripe = new THREE.Mesh(stripeGeo, stripeMat);
    stripe.position.y = 8 + i * 7;
    lighthouseGroup.add(stripe);
  }

  // 灯室
  const roomGeo = new THREE.CylinderGeometry(5.0, 4.0, 6.5, 16);
  const roomMat = new THREE.MeshBasicMaterial({ color: 0xfef6d8 });
  const room = new THREE.Mesh(roomGeo, roomMat);
  room.position.y = 44;
  lighthouseGroup.add(room);

  // 发光灯球
  const bulbGeo = new THREE.SphereGeometry(2.2, 20, 20);
  const bulbMat = new THREE.MeshBasicMaterial({
    color: 0xfffee0,
    transparent: true,
    opacity: 0.95
  });
  lighthouseBulb = new THREE.Mesh(bulbGeo, bulbMat);
  lighthouseBulb.position.y = 47;
  lighthouseGroup.add(lighthouseBulb);

  // 顶部红色航空警示灯（忽明忽暗）
  const warningGeo = new THREE.SphereGeometry(1.3, 16, 16);
  const warningMat = new THREE.MeshBasicMaterial({ color: 0xff2222 });
  const warningLight = new THREE.Mesh(warningGeo, warningMat);
  warningLight.position.y = 50.5;
  warningLight.name = 'warningLight';
  lighthouseGroup.add(warningLight);

  // 顶部小光晕 sprite
  const glowGeo = new THREE.PlaneGeometry(28, 28);
  const glowMat = new THREE.MeshBasicMaterial({
    color: 0xfffee0,
    transparent: true,
    opacity: 0.28,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    side: THREE.DoubleSide
  });
  const glowSprite = new THREE.Mesh(glowGeo, glowMat);
  glowSprite.position.y = 47;
  glowSprite.lookAt(0, 47, 1000);
  lighthouseGroup.add(glowSprite);

  // 探照灯光束：尖端固定在灯球，底端向远处海面/屏幕扫出
  const beamGeo = new THREE.ConeGeometry(34, 900, 32, 1, true);
  beamGeo.rotateX(-Math.PI / 2);       // 尖端朝 -z，底端朝 +z
  beamGeo.translate(0, 47, 450);       // 尖端移到 (0,47,0)，底端在 (0,47,900)

  // 光束径向渐变：近灯球处亮，远处淡出
  const gradCanvas = document.createElement('canvas');
  gradCanvas.width = 1;
  gradCanvas.height = 256;
  const gctx = gradCanvas.getContext('2d');
  const grad = gctx.createLinearGradient(0, 0, 0, 256);
  grad.addColorStop(0.0, 'rgba(255, 248, 220, 0.60)');
  grad.addColorStop(0.15, 'rgba(255, 248, 220, 0.28)');
  grad.addColorStop(0.55, 'rgba(255, 248, 220, 0.08)');
  grad.addColorStop(1.0, 'rgba(255, 248, 220, 0.0)');
  gctx.fillStyle = grad;
  gctx.fillRect(0, 0, 1, 256);
  const beamTex = new THREE.CanvasTexture(gradCanvas);

  const beamMat = new THREE.MeshBasicMaterial({
    color: 0xfff8cc,
    map: beamTex,
    transparent: true,
    opacity: 0.75,
    side: THREE.DoubleSide,
    depthWrite: false,
    blending: THREE.AdditiveBlending
  });
  lighthouseBeam = new THREE.Mesh(beamGeo, beamMat);
  lighthouseBeam.position.y = 0;
  lighthouseGroup.add(lighthouseBeam);

  // 聚光灯（给水面的高光，即使着色器没处理 spot 也能照亮其他标准材质）
  lighthouseSpot = new THREE.SpotLight(0xfff8cc, 0);
  lighthouseSpot.position.set(0, 47, 0);
  lighthouseSpot.angle = Math.PI / 7;
  lighthouseSpot.penumbra = 0.5;
  lighthouseSpot.decay = 1.0;
  lighthouseSpot.distance = 1400;
  lighthouseSpot.castShadow = false;
  lighthouseSpot.target.position.set(0, 0, 400);
  lighthouseGroup.add(lighthouseSpot);
  lighthouseGroup.add(lighthouseSpot.target);

    lighthouseGroup.visible = false; // 默认隐藏，由 applyModeToScene 控制
    scene.add(lighthouseGroup);
    console.log('[Ocean] lighthouse created');
  } catch (e) {
    console.error('[Ocean] createLighthouse failed:', e);
    lighthouseGroup = null;
    lighthouseBeam = null;
    lighthouseBulb = null;
    lighthouseSpot = null;
  }
}

// ============================================================
// 海洋 — 32 层 Gerstner + Jacobian 白沫 + FBM 微表面
// ============================================================
function createOcean() {
  const { segments, size } = OCEAN_CONFIG;
  const waves = BASE_WAVES;

  oceanGeometry = new THREE.PlaneGeometry(size, size, segments, segments);
  oceanGeometry.rotateX(-Math.PI / 2);

  const N = WAVE_COUNT;

  const vertexShader = `
    uniform float uTime;
    uniform float uAmpScale;
    uniform vec2 uWaveDir[${N}];
    uniform float uWaveAmp[${N}];
    uniform float uWaveK[${N}];
    uniform float uWaveSpeed[${N}];
    uniform float uWaveQ[${N}];

    varying vec3 vWorldPos;
    varying vec3 vNormal;
    varying float vHeight;
    varying float vFoam;
    varying vec2 vWorldXZ;

    float hash(vec2 p) {
      return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
    }
    float noise(vec2 p) {
      vec2 i = floor(p);
      vec2 f = fract(p);
      f = f * f * (3.0 - 2.0 * f);
      float a = hash(i);
      float b = hash(i + vec2(1.0, 0.0));
      float c = hash(i + vec2(0.0, 1.0));
      float d = hash(i + vec2(1.0, 1.0));
      return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
    }
    float fbm(vec2 p) {
      float v = 0.0;
      float a = 0.5;
      for (int i = 0; i < 5; i++) {
        v += a * noise(p);
        p *= 2.0;
        a *= 0.5;
      }
      return v;
    }

    void main() {
      vec3 pos = position;
      vec3 tang = vec3(1.0, 0.0, 0.0);
      vec3 bitang = vec3(0.0, 0.0, 1.0);

      const float g = 9.81;
      float ddx_x = 0.0;
      float ddx_z = 0.0;
      float ddz_x = 0.0;
      float ddz_z = 0.0;

      for (int i = 0; i < ${N}; i++) {
        float k = uWaveK[i];
        float w = sqrt(g * k);
        float amp = uWaveAmp[i] * uAmpScale;
        float q = uWaveQ[i];
        vec2 d = uWaveDir[i];

        float phase = k * (d.x * pos.x + d.y * pos.z) - w * uTime * uWaveSpeed[i];
        float c = cos(phase);
        float s = sin(phase);

        pos.y += amp * c;
        float qampc = q * amp * c;
        pos.x += qampc * d.x;
        pos.z += qampc * d.y;

        float wa = w * amp;
        float qwa = q * wa;
        float dx = d.x;
        float dz = d.y;

        tang.y += -dx * wa * s;
        tang.x += -dx * dx * qwa * s;
        tang.z += -dx * dz * qwa * s;

        bitang.y += -dz * wa * s;
        bitang.x += -dx * dz * qwa * s;
        bitang.z += -dz * dz * qwa * s;

        ddx_x += -qwa * dx * dx * s;
        ddx_z += -qwa * dx * dz * s;
        ddz_x += -qwa * dz * dx * s;
        ddz_z += -qwa * dz * dz * s;
      }

      float J = (1.0 + ddx_x) * (1.0 + ddz_z) - ddx_z * ddz_x;
      vFoam = smoothstep(0.62, 0.18, J);

      vec2 detailUv = pos.xz * 0.48 + uTime * 0.022;
      float n0 = fbm(detailUv);
      float nx = fbm(detailUv + vec2(0.008, 0.0));
      float nz = fbm(detailUv + vec2(0.0, 0.008));
      vec3 microN = normalize(vec3((n0 - nx) * 2.6, 0.55, (n0 - nz) * 2.6));

      vWorldPos = (modelMatrix * vec4(pos, 1.0)).xyz;
      vNormal = normalize(cross(bitang, tang) + microN * 0.55);
      vHeight = pos.y;
      vWorldXZ = pos.xz;

      gl_Position = projectionMatrix * viewMatrix * modelMatrix * vec4(pos, 1.0);
    }
  `;

  const fragmentShader = `
    uniform vec3 uDeepColor;
    uniform vec3 uShallowColor;
    uniform vec3 uFoamColor;
    uniform vec3 uSunColor;
    uniform vec3 uSunDir;
    uniform vec3 uCameraPos;
    uniform vec3 uHorizonColor;
    uniform float uRoughness;
    uniform float uFogNear;
    uniform float uFogFar;
    uniform float uSunGlintStrength;
    uniform samplerCube uEnvMap;
    uniform float uTime;

    varying vec3 vWorldPos;
    varying vec3 vNormal;
    varying float vHeight;
    varying float vFoam;
    varying vec2 vWorldXZ;

    float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123); }
    float noise(vec2 p) {
      vec2 i = floor(p); vec2 f = fract(p);
      f = f * f * (3.0 - 2.0 * f);
      return mix(mix(hash(i), hash(i + vec2(1,0)), f.x),
                 mix(hash(i + vec2(0,1)), hash(i + vec2(1,1)), f.x), f.y);
    }
    float fbm(vec2 p) {
      float v = 0.0, a = 0.5;
      for (int i = 0; i < 5; i++) { v += a * noise(p); p *= 2.0; a *= 0.5; }
      return v;
    }

    float D_GGX(float NoH, float roughness) {
      float a = roughness * roughness;
      float a2 = a * a;
      float d = (NoH * NoH) * (a2 - 1.0) + 1.0;
      return a2 / (3.14159265 * d * d);
    }

    float G_Smith(float NoV, float NoL, float roughness) {
      float a = roughness * roughness;
      float ggxV = NoV * (NoL * (1.0 - a) + a);
      float ggxL = NoL * (NoV * (1.0 - a) + a);
      return 0.5 / (ggxV + ggxL + 0.001);
    }

    vec3 F_Schlick(float HoV, vec3 F0) {
      return F0 + (1.0 - F0) * pow(1.0 - HoV, 5.0);
    }

    void main() {
      vec3 N = normalize(vNormal);
      vec3 V = normalize(uCameraPos - vWorldPos);
      vec3 L = normalize(uSunDir);
      vec3 H = normalize(V + L);
      vec3 R = reflect(-V, N);

      float NoV = max(0.001, dot(N, V));
      float NoL = max(0.0, dot(N, L));
      float NoH = max(0.0, dot(N, H));
      float HoV = max(0.0, dot(H, V));

      float dist = length(vWorldPos.xz);
      float depthFactor = smoothstep(0.0, 260.0, dist) * 0.72 + 0.18;
      float crestFactor = smoothstep(-0.7, 1.0, vHeight) * 0.45;
      vec3 waterColor = mix(uShallowColor, uDeepColor, depthFactor);
      waterColor = mix(waterColor, uShallowColor * 1.15, crestFactor);

      // 夕阳：远处水面向地平线/sunColor 色调交融（碧蓝底 + 橙红高光）
      float sunLow = smoothstep(0.22, 0.0, L.y);
      float horizonView = pow(1.0 - V.y, 2.2) * smoothstep(0.0, 0.35, NoL);
      waterColor = mix(waterColor, uSunColor * 1.1, horizonView * 0.38 * sunLow);

      vec3 F0 = vec3(0.02);
      vec3 F = F_Schlick(HoV, F0);

      vec3 skyReflect = textureCube(uEnvMap, R).rgb;
      float fresnel = F0.x + (1.0 - F0.x) * pow(1.0 - NoV, 5.0);

      float D = D_GGX(NoH, uRoughness);
      float G = G_Smith(NoV, NoL, uRoughness);
      vec3 specular = uSunColor * D * F * G * 2.2;

      float reflectSun = max(0.0, dot(R, L));
      float sunGlint = pow(reflectSun, 180.0) * smoothstep(0.0, 0.40, NoL) * uSunGlintStrength;
      vec3 glintColor = uSunColor * sunGlint;

      // 物理微表面波光：连续分布，由 FBM 微法线 + 太阳反射方向共同驱动
      vec2 glitterUv = vWorldXZ * 1.4 + uTime * 0.08;
      float microNoise = fbm(glitterUv);
      float microNoise2 = fbm(glitterUv * 3.2 + vec2(17.3, -5.7));
      float combined = 0.5 * microNoise + 0.5 * microNoise2;
      float sparkleMask = smoothstep(0.42, 0.78, combined);
      float microFacet = pow(max(0.0, dot(N, H)), 80.0);
      float sparkle = microFacet * sparkleMask * pow(reflectSun, 4.0);
      sparkle *= smoothstep(0.0, 0.35, NoL) * pow(1.0 - NoV, 0.25);

      vec3 sss = uShallowColor * pow(1.0 - NoL, 3.0) * 0.10 * max(0.0, vHeight + 0.6);

      float foam = vFoam * (0.5 + 0.5 * fbm(vWorldXZ * 0.8 + uTime * 0.05));
      foam = smoothstep(0.35, 0.90, foam);

      vec3 diffuse = waterColor * (0.10 + 0.58 * NoL);
      vec3 color = diffuse + skyReflect * fresnel * 0.75 + specular + glintColor + sss;
      color += uSunColor * sparkle * 0.35;
      color = mix(color, uFoamColor, foam * 0.55);

      float fog = smoothstep(uFogNear, uFogFar, dist);
      color = mix(color, uHorizonColor, fog * 0.48);

      gl_FragColor = vec4(color, 1.0);
    }
  `;

  oceanMaterial = new THREE.ShaderMaterial({
    vertexShader,
    fragmentShader,
    uniforms: {
      uTime: { value: 0 },
      uAmpScale: { value: mode.waveAmpScale },
      uWaveDir: { value: waves.map(w => w.dir) },
      uWaveAmp: { value: waves.map(w => w.amp) },
      uWaveK: { value: waves.map(w => 2.0 * Math.PI / w.waveLen) },
      uWaveSpeed: { value: waves.map(w => w.speed) },
      uWaveQ: { value: waves.map(w => w.q) },
      uDeepColor: { value: mode.deepColor },
      uShallowColor: { value: mode.shallowColor },
      uFoamColor: { value: mode.foamColor },
      uSunColor: { value: mode.sunColor },
      uSunDir: { value: mode.sunDir },
      uCameraPos: { value: camera.position },
      uHorizonColor: { value: mode.horizonColor },
      uRoughness: { value: mode.roughness },
      uFogNear: { value: mode.fogNear },
      uFogFar: { value: mode.fogFar },
      uSunGlintStrength: { value: mode.sunGlintStrength },
      uEnvMap: { value: envCubeRenderTarget ? envCubeRenderTarget.texture : null }
    }
  });

  oceanMesh = new THREE.Mesh(oceanGeometry, oceanMaterial);
  oceanMesh.position.set(0, -0.2, 0);
  scene.add(oceanMesh);
}

// ============================================================
// 水面闪光粒子（保留但减少，并绑定到太阳反光带区域）
// ============================================================
function createSparkles() {
  const count = OCEAN_CONFIG.sparkleCount;
  if (count <= 0) {
    if (sparkleSystem) {
      scene.remove(sparkleSystem);
      if (sparkleGeo) sparkleGeo.dispose();
      if (sparkleMat) sparkleMat.dispose();
      sparkleSystem = null;
      sparkleGeo = null;
      sparkleMat = null;
    }
    return;
  }
  const positions = new Float32Array(count * 3);
  const sizes = new Float32Array(count);
  const phases = new Float32Array(count);
  const intensities = new Float32Array(count);

  const sunDir = mode.sunDir.clone();

  for (let i = 0; i < count; i++) {
    const dist = 20 + Math.pow(Math.random(), 0.7) * 320;
    const bandWidth = 4.0 + dist * 0.45;
    const angle = (Math.random() - 0.5) * 1.6;

    const reflectZ = -dist * 0.55;
    const reflectX = Math.tan(angle) * bandWidth * 0.5;

    positions[i*3] = reflectX + (Math.random() - 0.5) * bandWidth * 0.6;
    positions[i*3+1] = 0.05 + Math.random() * 0.8;
    positions[i*3+2] = reflectZ + (Math.random() - 0.5) * 55;

    const centerDist = Math.abs(angle);
    sizes[i] = (0.5 + (1.0 - centerDist / 2.0) * 1.6 + Math.random() * 0.8) * OCEAN_CONFIG.sparkleSize;
    phases[i] = Math.random() * Math.PI * 2;
    intensities[i] = 0.25 + (1.0 - centerDist / 2.0) * 0.65 + Math.random() * 0.35;
  }

  sparkleGeo = new THREE.BufferGeometry();
  sparkleGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  sparkleGeo.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1));
  sparkleGeo.setAttribute('aPhase', new THREE.BufferAttribute(phases, 1));
  sparkleGeo.setAttribute('aIntensity', new THREE.BufferAttribute(intensities, 1));

  const vertexShader = `
    attribute float aSize;
    attribute float aPhase;
    attribute float aIntensity;
    uniform float uTime;
    uniform float uPixelRatio;
    varying float vAlpha;
    void main() {
      float fast = sin(uTime * 2.6 + aPhase * 7.0);
      float slow = sin(uTime * 0.55 + aPhase * 3.0);
      float twinkle = pow(0.5 + 0.5 * fast, 2.0) * (0.55 + 0.45 * slow);
      vAlpha = twinkle * aIntensity;
      vec4 mv = modelViewMatrix * vec4(position, 1.0);
      gl_PointSize = aSize * uPixelRatio * (160.0 / -mv.z);
      gl_Position = projectionMatrix * mv;
    }
  `;

  const fragmentShader = `
    uniform vec3 uSparkleColor;
    varying float vAlpha;
    void main() {
      vec2 uv = gl_PointCoord - 0.5;
      float d = length(uv);
      if (d > 0.5) discard;
      float core = 1.0 - smoothstep(0.0, 0.12, d);
      float glow = 1.0 - smoothstep(0.0, 0.5, d);
      float crossGlow = max(0.0, 1.0 - abs(uv.x) * 8.0) * max(0.0, 1.0 - abs(uv.y) * 8.0);
      float star = core * 2.0 + glow * 0.9 + crossGlow * 0.35;
      gl_FragColor = vec4(uSparkleColor * (1.0 + core * 1.2), vAlpha * star);
    }
  `;

  sparkleMat = new THREE.ShaderMaterial({
    vertexShader,
    fragmentShader,
    uniforms: {
      uTime: { value: 0 },
      uPixelRatio: { value: renderer.getPixelRatio() },
      uSparkleColor: { value: mode.sparkleColor }
    },
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending
  });

  sparkleSystem = new THREE.Points(sparkleGeo, sparkleMat);
  sparkleSystem.position.copy(oceanMesh.position);
  scene.add(sparkleSystem);
}

// ============================================================
// 后处理 — 简易 Extract + 双向高斯模糊 + 合成
// ============================================================
function initPostProcessing() {
  const w = renderer.domElement.width;
  const h = renderer.domElement.height;

  const options = {
    minFilter: THREE.LinearFilter,
    magFilter: THREE.LinearFilter,
    format: THREE.RGBAFormat,
    type: THREE.HalfFloatType,
    stencilBuffer: false
  };

  try {
    sceneRenderTarget = new THREE.WebGLRenderTarget(w, h, options);
  } catch (e) {
    options.type = THREE.FloatType;
    try { sceneRenderTarget = new THREE.WebGLRenderTarget(w, h, options); }
    catch (e2) { options.type = THREE.UnsignedByteType; sceneRenderTarget = new THREE.WebGLRenderTarget(w, h, options); }
  }

  const bw = Math.max(1, Math.floor(w * OCEAN_CONFIG.bloomDownScale));
  const bh = Math.max(1, Math.floor(h * OCEAN_CONFIG.bloomDownScale));

  const bloomOptions = {
    minFilter: THREE.LinearFilter,
    magFilter: THREE.LinearFilter,
    format: THREE.RGBAFormat,
    type: THREE.HalfFloatType,
    stencilBuffer: false
  };
  try {
    bloomExtractTarget = new THREE.WebGLRenderTarget(bw, bh, bloomOptions);
    blurTargetH = new THREE.WebGLRenderTarget(bw, bh, bloomOptions);
    blurTargetV = new THREE.WebGLRenderTarget(bw, bh, bloomOptions);
  } catch (e) {
    bloomOptions.type = THREE.FloatType;
    try {
      bloomExtractTarget = new THREE.WebGLRenderTarget(bw, bh, bloomOptions);
      blurTargetH = new THREE.WebGLRenderTarget(bw, bh, bloomOptions);
      blurTargetV = new THREE.WebGLRenderTarget(bw, bh, bloomOptions);
    } catch (e2) {
      bloomOptions.type = THREE.UnsignedByteType;
      bloomExtractTarget = new THREE.WebGLRenderTarget(bw, bh, bloomOptions);
      blurTargetH = new THREE.WebGLRenderTarget(bw, bh, bloomOptions);
      blurTargetV = new THREE.WebGLRenderTarget(bw, bh, bloomOptions);
    }
  }

  const vertexPass = `
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = vec4(position.xy, 0.0, 1.0);
    }
  `;

  bloomExtractMat = new THREE.ShaderMaterial({
    vertexShader: vertexPass,
    fragmentShader: `
      uniform sampler2D tScene;
      uniform float uThreshold;
      varying vec2 vUv;
      void main() {
        vec3 c = texture2D(tScene, vUv).rgb;
        float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
        float contrib = max(0.0, l - uThreshold) / max(l, 0.0001);
        gl_FragColor = vec4(c * contrib, 1.0);
      }
    `,
    uniforms: { tScene: { value: sceneRenderTarget.texture }, uThreshold: { value: mode.bloomThreshold } }
  });

  bloomBlurHMat = new THREE.ShaderMaterial({
    vertexShader: vertexPass,
    fragmentShader: `
      uniform sampler2D tInput;
      uniform vec2 uTexelSize;
      varying vec2 vUv;
      void main() {
        vec3 c = texture2D(tInput, vUv).rgb * 0.2270270270;
        c += texture2D(tInput, vUv + vec2(uTexelSize.x * 1.0, 0.0)).rgb * 0.3162162162;
        c += texture2D(tInput, vUv - vec2(uTexelSize.x * 1.0, 0.0)).rgb * 0.3162162162;
        c += texture2D(tInput, vUv + vec2(uTexelSize.x * 2.0, 0.0)).rgb * 0.0702702703;
        c += texture2D(tInput, vUv - vec2(uTexelSize.x * 2.0, 0.0)).rgb * 0.0702702703;
        gl_FragColor = vec4(c, 1.0);
      }
    `,
    uniforms: { tInput: { value: bloomExtractTarget.texture }, uTexelSize: { value: new THREE.Vector2(1 / bw, 1 / bh) } }
  });

  bloomBlurVMat = new THREE.ShaderMaterial({
    vertexShader: vertexPass,
    fragmentShader: `
      uniform sampler2D tInput;
      uniform vec2 uTexelSize;
      varying vec2 vUv;
      void main() {
        vec3 c = texture2D(tInput, vUv).rgb * 0.2270270270;
        c += texture2D(tInput, vUv + vec2(0.0, uTexelSize.y * 1.0)).rgb * 0.3162162162;
        c += texture2D(tInput, vUv - vec2(0.0, uTexelSize.y * 1.0)).rgb * 0.3162162162;
        c += texture2D(tInput, vUv + vec2(0.0, uTexelSize.y * 2.0)).rgb * 0.0702702703;
        c += texture2D(tInput, vUv - vec2(0.0, uTexelSize.y * 2.0)).rgb * 0.0702702703;
        gl_FragColor = vec4(c, 1.0);
      }
    `,
    uniforms: { tInput: { value: blurTargetH.texture }, uTexelSize: { value: new THREE.Vector2(1 / bw, 1 / bh) } }
  });

  combineMat = new THREE.ShaderMaterial({
    vertexShader: vertexPass,
    fragmentShader: `
      uniform sampler2D tScene;
      uniform sampler2D tBloom;
      uniform float uBloomStrength;
      varying vec2 vUv;
      void main() {
        vec3 scene = texture2D(tScene, vUv).rgb;
        vec3 bloom = texture2D(tBloom, vUv).rgb;
        vec3 c = scene + bloom * uBloomStrength;
        c *= 1.18;
        c = c / (c + vec3(1.0));
        c = pow(c, vec3(0.88));
        gl_FragColor = vec4(c, 1.0);
      }
    `,
    uniforms: {
      tScene: { value: sceneRenderTarget.texture },
      tBloom: { value: blurTargetV.texture },
      uBloomStrength: { value: mode.bloomStrength }
    }
  });

  postQuad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), combineMat);
  postScene = new THREE.Scene();
  postScene.add(postQuad);
  postCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
}

function resizePostProcessing(w, h) {
  if (!sceneRenderTarget) return;
  sceneRenderTarget.setSize(w, h);
  const bw = Math.max(1, Math.floor(w * OCEAN_CONFIG.bloomDownScale));
  const bh = Math.max(1, Math.floor(h * OCEAN_CONFIG.bloomDownScale));
  bloomExtractTarget.setSize(bw, bh);
  blurTargetH.setSize(bw, bh);
  blurTargetV.setSize(bw, bh);
  bloomBlurHMat.uniforms.uTexelSize.value.set(1 / bw, 1 / bh);
  bloomBlurVMat.uniforms.uTexelSize.value.set(1 / bw, 1 / bh);
}

function renderPostProcessing() {
  // 1. 提取亮部
  postQuad.material = bloomExtractMat;
  renderer.setRenderTarget(bloomExtractTarget);
  renderer.render(postScene, postCamera);

  // 2. 多次双向模糊
  for (let i = 0; i < OCEAN_CONFIG.bloomIterations; i++) {
    postQuad.material = bloomBlurHMat;
    bloomBlurHMat.uniforms.tInput.value = (i === 0) ? bloomExtractTarget.texture : blurTargetV.texture;
    renderer.setRenderTarget(blurTargetH);
    renderer.render(postScene, postCamera);

    postQuad.material = bloomBlurVMat;
    bloomBlurVMat.uniforms.tInput.value = blurTargetH.texture;
    renderer.setRenderTarget(blurTargetV);
    renderer.render(postScene, postCamera);
  }

  // 3. 合成到屏幕
  postQuad.material = combineMat;
  combineMat.uniforms.tBloom.value = blurTargetV.texture;
  renderer.setRenderTarget(null);
  renderer.render(postScene, postCamera);
}

// ============================================================
// 光照
// ============================================================
function setupLighting() {
  ambientLight = new THREE.AmbientLight(mode.ambientColor, mode.ambientIntensity);
  scene.add(ambientLight);

  sunLight = new THREE.DirectionalLight(mode.sunColor, mode.sunIntensity);
  sunLight.position.copy(mode.sunDir).multiplyScalar(1000);
  scene.add(sunLight);
}

// ============================================================
// 应用模式
// ============================================================
function applyModeToScene() {
  const sunPos = mode.sunDir.clone().multiplyScalar(1200);

  if (skyMaterial) {
    skyMaterial.uniforms.topColor.value.copy(mode.skyTop);
    skyMaterial.uniforms.midColor.value.copy(mode.skyMid);
    skyMaterial.uniforms.bottomColor.value.copy(mode.skyBottom);
    skyMaterial.uniforms.sunDir.value.copy(mode.sunDir);
    skyMaterial.uniforms.sunColor.value.copy(mode.sunColor);
    skyMaterial.uniforms.sunGlowColor.value.copy(mode.sunGlowColor);
    skyMaterial.uniforms.sunDiskSize.value = mode.sunDiskSize;
  }

  if (sunMesh) {
    sunMesh.material.color.copy(mode.sunColor);
    sunMesh.geometry.dispose();
    sunMesh.geometry = new THREE.SphereGeometry(mode.sunDiskSize * 0.9, 32, 32);
    sunMesh.position.copy(sunPos);
  }
  if (sunGlow) {
    sunGlow.material.color.copy(mode.sunGlowColor);
    sunGlow.geometry.dispose();
    sunGlow.geometry = new THREE.SphereGeometry(mode.sunDiskSize * 2.4, 32, 32);
    sunGlow.position.copy(sunPos);
  }
  if (sunGlowOuter) {
    sunGlowOuter.material.color.copy(mode.sunGlowColor);
    sunGlowOuter.geometry.dispose();
    sunGlowOuter.geometry = new THREE.SphereGeometry(mode.sunDiskSize * 5.5, 32, 32);
    sunGlowOuter.position.copy(sunPos);
  }
  if (sunGlowHalo) {
    sunGlowHalo.material.color.copy(mode.sunGlowColor);
    sunGlowHalo.geometry.dispose();
    sunGlowHalo.geometry = new THREE.SphereGeometry(mode.sunDiskSize * 14.0, 32, 32);
    sunGlowHalo.position.copy(sunPos);
  }

  if (ambientLight) {
    ambientLight.color.copy(mode.ambientColor);
    ambientLight.intensity = mode.ambientIntensity;
  }
  if (sunLight) {
    sunLight.color.copy(mode.sunColor);
    sunLight.intensity = mode.sunIntensity;
    sunLight.position.copy(mode.sunDir).multiplyScalar(1000);
  }

  if (starsMat) {
    starsMat.uniforms.uStarOpacity.value = mode.starOpacity;
  }
  if (starsSystem) {
    starsSystem.visible = mode.starOpacity > 0.05;
  }

  if (oceanMaterial) {
    oceanMaterial.uniforms.uDeepColor.value.copy(mode.deepColor);
    oceanMaterial.uniforms.uShallowColor.value.copy(mode.shallowColor);
    oceanMaterial.uniforms.uFoamColor.value.copy(mode.foamColor);
    oceanMaterial.uniforms.uSunColor.value.copy(mode.sunColor);
    oceanMaterial.uniforms.uSunDir.value.copy(mode.sunDir);
    oceanMaterial.uniforms.uHorizonColor.value.copy(mode.horizonColor);
    oceanMaterial.uniforms.uRoughness.value = mode.roughness;
    oceanMaterial.uniforms.uFogNear.value = mode.fogNear;
    oceanMaterial.uniforms.uFogFar.value = mode.fogFar;
    oceanMaterial.uniforms.uAmpScale.value = mode.waveAmpScale;
    oceanMaterial.uniforms.uSunGlintStrength.value = mode.sunGlintStrength;
  }

  if (sparkleMat) {
    sparkleMat.uniforms.uSparkleColor.value.copy(mode.sparkleColor);
  }

  if (bloomExtractMat) {
    bloomExtractMat.uniforms.uThreshold.value = mode.bloomThreshold;
  }
  if (combineMat) {
    combineMat.uniforms.uBloomStrength.value = mode.bloomStrength;
  }

  if (renderer) {
    renderer.setClearColor(mode.horizonColor, 1.0);
  }

  // 灯塔：夜晚全开，黄昏半亮，白天隐藏
  if (lighthouseGroup) {
    if (mode.name === 'night') {
      lighthouseGroup.visible = true;
      lighthouseBaseOpacity = 0.22;
      lighthouseBaseIntensity = 3.5;
      if (lighthouseBeam) lighthouseBeam.material.color.setRGB(1.0, 0.92, 0.65);
    } else if (mode.name === 'sunset') {
      lighthouseGroup.visible = true;
      lighthouseBaseOpacity = 0.14;
      lighthouseBaseIntensity = 0.8;
      if (lighthouseBeam) lighthouseBeam.material.color.setRGB(1.0, 0.95, 0.72);
    } else {
      lighthouseGroup.visible = false;
      lighthouseBaseOpacity = 0.0;
      lighthouseBaseIntensity = 0.0;
    }
  }

  updateEnvironmentMap();
}

// ============================================================
// 模式切换
// ============================================================
function setMode(newModeKey) {
  if (!MODES[newModeKey] || newModeKey === currentModeKey) return;
  currentModeKey = newModeKey;
  mode = MODES[newModeKey];

  if (sparkleSystem) {
    scene.remove(sparkleSystem);
    sparkleGeo.dispose();
    sparkleMat.dispose();
    createSparkles();
  }

  applyModeToScene();
  console.log('[Ocean] 切换模式:', newModeKey);
}

function onMessage(e) {
  if (e.data && e.data.type === 'ocean-set-mode' && e.data.mode) {
    setMode(e.data.mode);
  }
}

// ============================================================
// 动画循环
// ============================================================
function animate() {
  requestAnimationFrame(animate);

  if (!isVisible) return;

  time += 0.0052;

  if (oceanMaterial) {
    oceanMaterial.uniforms.uTime.value = time;
    oceanMaterial.uniforms.uCameraPos.value.copy(camera.position);
  }

  if (sparkleMat) {
    sparkleMat.uniforms.uTime.value = time;
  }

  if (starsMat) {
    starsMat.uniforms.uTime.value = time;
  }

  const sunBase = mode.sunDir.clone();
  const sunX = sunBase.x + Math.sin(time * 0.025) * 0.025;
  const sunY = sunBase.y + Math.cos(time * 0.018) * 0.012;
  const sunZ = sunBase.z + Math.sin(time * 0.012) * 0.018;
  const sunDir = new THREE.Vector3(sunX, sunY, sunZ).normalize();
  const sunPos = sunDir.clone().multiplyScalar(1200);

  if (sunMesh) sunMesh.position.copy(sunPos);
  if (sunGlow) sunGlow.position.copy(sunPos);
  if (sunGlowOuter) sunGlowOuter.position.copy(sunPos);
  if (sunGlowHalo) sunGlowHalo.position.copy(sunPos);
  if (sunLight) sunLight.position.copy(sunDir).multiplyScalar(1000);
  if (oceanMaterial) oceanMaterial.uniforms.uSunDir.value.copy(sunDir);
  if (skyMaterial) skyMaterial.uniforms.sunDir.value.copy(sunDir);

  if (starsSystem) {
    starsSystem.rotation.y += 0.00008;
  }

  // 灯塔探照灯 360° 旋转 + 扫到屏幕时闪光
  if (lighthouseBeam && lighthouseGroup && lighthouseGroup.visible) {
    const beamAngle = time * 0.55; // 更快的 360° 扫描
    lighthouseBeam.rotation.y = beamAngle;

    // 光束当前世界方向（灯塔 group 无旋转，直接由 beam rotation 决定）
    const beamDir = new THREE.Vector3(Math.sin(beamAngle), -0.18, Math.cos(beamAngle)).normalize();
    const toCamera = new THREE.Vector3().subVectors(camera.position, lighthouseGroup.position).normalize();
    const align = Math.max(0.0, beamDir.dot(toCamera));

    // 当光束正对相机时触发闪光
    const inBeam = align > 0.985 ? 1.0 : 0.0;
    const flashTarget = inBeam * 0.62;
    if (flashEl) {
      const current = parseFloat(flashEl.style.opacity || '0');
      flashEl.style.opacity = Math.max(current * 0.92, flashTarget).toString();
    }

    const pulse = 0.5 + 0.5 * Math.sin(time * 1.6);
    const baseOp = lighthouseBaseOpacity * (0.35 + 0.65 * pulse);
    // 扫到屏幕时光束更亮
    lighthouseBeam.material.opacity = baseOp + inBeam * 0.35;
    if (lighthouseBulb) {
      const intensity = 0.55 + 0.45 * pulse + inBeam * 0.45;
      lighthouseBulb.material.color.setRGB(intensity, intensity * 0.96, intensity * 0.82);
    }
    const warningLight = lighthouseGroup.getObjectByName('warningLight');
    if (warningLight) {
      const wPulse = 0.4 + 0.6 * Math.sin(time * 3.0);
      warningLight.material.color.setRGB(0.5 + wPulse * 0.5, 0.1, 0.1);
      warningLight.scale.setScalar(0.8 + wPulse * 0.4);
    }
    if (lighthouseSpot) {
      lighthouseSpot.intensity = lighthouseBaseIntensity * (0.3 + 0.7 * pulse + inBeam * 1.5);
      const spotDir = beamDir.clone();
      lighthouseSpot.target.position.copy(lighthouseSpot.position).add(spotDir.multiplyScalar(900));
      lighthouseSpot.target.updateMatrixWorld();
    }
  } else if (flashEl) {
    flashEl.style.opacity = '0';
  }

  const driftX = Math.sin(time * 0.035) * 2.5;
  const driftY = Math.cos(time * 0.03) * 0.25;
  camera.position.x = driftX;
  camera.position.y = 6.8 + driftY;
  camera.lookAt(driftX * 0.2, 0.35 + driftY * 0.08, 0);

  renderer.setRenderTarget(sceneRenderTarget);
  renderer.render(scene, camera);
  renderPostProcessing();
}

function onWindowResize() {
  const w = window.innerWidth || 1;
  const h = window.innerHeight || 1;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
  resizePostProcessing(w, h);
  if (sparkleMat) sparkleMat.uniforms.uPixelRatio.value = renderer.getPixelRatio();
  if (starsMat) starsMat.uniforms.uPixelRatio.value = renderer.getPixelRatio();
}

function onVisibilityChange() {
  isVisible = !document.hidden;
}

function showError(msg) {
  loadingEl.style.display = 'none';
  errorEl.textContent = msg;
  errorEl.style.display = 'block';
  errorEl.style.opacity = '1';
  try {
    if (window.parent && window.parent !== window) {
      window.parent.postMessage({ type: 'ocean-error', message: msg }, '*');
    }
  } catch (e) {}

  if (errorHideTimer) clearTimeout(errorHideTimer);
  errorHideTimer = setTimeout(() => {
    errorEl.style.opacity = '0';
    setTimeout(() => { errorEl.style.display = 'none'; }, 1000);
  }, 5000);
}
