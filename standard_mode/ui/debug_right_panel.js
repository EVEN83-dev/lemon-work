(function() {
  var result = {};
  
  // 1. body 状态
  result.body = {
    classes: document.body ? Array.from(document.body.classList) : [],
    position: document.body ? getComputedStyle(document.body).position : 'N/A',
    width: document.body ? document.body.offsetWidth : 0,
    height: document.body ? document.body.offsetHeight : 0,
    innerWidth: window.innerWidth,
    innerHeight: window.innerHeight
  };
  
  // 2. #wallpaper-layer
  var wl = document.getElementById('wallpaper-layer');
  result.wallpaperLayer = wl ? {
    exists: true,
    display: getComputedStyle(wl).display,
    position: getComputedStyle(wl).position,
    width: wl.offsetWidth,
    height: wl.offsetHeight,
    zIndex: getComputedStyle(wl).zIndex,
    isolation: getComputedStyle(wl).isolation,
    overflow: getComputedStyle(wl).overflow,
    childCount: wl.children.length
  } : { exists: false };
  
  // 3. #nebula canvas
  var neb = document.getElementById('nebula');
  result.nebula = neb ? {
    exists: true,
    width: neb.width,
    height: neb.height,
    offsetWidth: neb.offsetWidth,
    offsetHeight: neb.offsetHeight,
    opacity: neb.style.opacity || getComputedStyle(neb).opacity,
    display: getComputedStyle(neb).display,
    position: getComputedStyle(neb).position,
    parent: neb.parentElement ? neb.parentElement.id : 'N/A'
  } : { exists: false };
  
  // 4. #starfield canvas
  var sf = document.getElementById('starfield');
  result.starfield = sf ? {
    exists: true,
    width: sf.width,
    height: sf.height,
    offsetWidth: sf.offsetWidth,
    offsetHeight: sf.offsetHeight,
    opacity: sf.style.opacity || getComputedStyle(sf).opacity,
    display: getComputedStyle(sf).display,
    position: getComputedStyle(sf).position,
    parent: sf.parentElement ? sf.parentElement.id : 'N/A',
    rafRunning: (typeof _starfieldRAF !== 'undefined' && _starfieldRAF !== null)
  } : { exists: false };
  
  // 5. #content
  var ct = document.getElementById('content');
  result.content = ct ? {
    exists: true,
    display: getComputedStyle(ct).display,
    position: getComputedStyle(ct).position,
    width: ct.offsetWidth,
    height: ct.offsetHeight,
    zIndex: getComputedStyle(ct).zIndex,
    isolation: getComputedStyle(ct).isolation,
    background: getComputedStyle(ct).background,
    pointerEvents: getComputedStyle(ct).pointerEvents,
    flex: getComputedStyle(ct).flex,
    minHeight: getComputedStyle(ct).minHeight,
    overflow: getComputedStyle(ct).overflow,
    top: getComputedStyle(ct).top,
    left: getComputedStyle(ct).left
  } : { exists: false };
  
  // 6. .output-area
  var oa = document.querySelector('.output-area');
  result.outputArea = oa ? {
    exists: true,
    width: oa.offsetWidth,
    height: oa.offsetHeight,
    display: getComputedStyle(oa).display,
    background: getComputedStyle(oa).background
  } : { exists: false };
  
  // 7. .output-messages
  var om = document.querySelector('.output-messages');
  result.outputMessages = om ? {
    exists: true,
    width: om.offsetWidth,
    height: om.offsetHeight,
    childCount: om.children.length,
    display: getComputedStyle(om).display
  } : { exists: false };
  
  // 8. .input-area
  var ia = document.querySelector('.input-area');
  result.inputArea = ia ? {
    exists: true,
    width: ia.offsetWidth,
    height: ia.offsetHeight,
    display: getComputedStyle(ia).display
  } : { exists: false };
  
  // 9. .logo-area
  var la = document.querySelector('.logo-area');
  result.logoArea = la ? {
    exists: true,
    width: la.offsetWidth,
    height: la.offsetHeight,
    display: getComputedStyle(la).display
  } : { exists: false };
  
  // 10. 检查是否有 _starfieldRAF
  result.starfieldRAF = {
    defined: typeof _starfieldRAF !== 'undefined',
    value: typeof _starfieldRAF !== 'undefined' ? _starfieldRAF : 'undefined',
    wallpaperMode: typeof _wallpaperMode !== 'undefined' ? _wallpaperMode : 'undefined',
    wallpaperTheme: typeof _wallpaperTheme !== 'undefined' ? _wallpaperTheme : 'undefined'
  };
  
  // 11. #oceanfield
  var oc = document.getElementById('oceanfield');
  result.oceanfield = oc ? {
    exists: true,
    display: getComputedStyle(oc).display,
    opacity: oc.style.opacity || getComputedStyle(oc).opacity,
    src: oc.src
  } : { exists: false };
  
  return JSON.stringify(result);
})();
