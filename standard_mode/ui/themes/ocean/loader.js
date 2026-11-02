/*
 * Lemon Code 3D WebGPU 海洋壁纸加载器（经典脚本，供 mimo_page.html 使用）
 * 职责：iframe 挂载/卸载 themes/ocean 的 WebGPU 海面，
 *       就绪前隐藏、失败/超时自动回退（由调用方传入 onFail），
 *       并向 iframe 桥接 day / sunset / night 三态切换。
 */
(function () {
  'use strict';

  var iframe = null;
  var readyListener = null;
  var readyTimer = null;
  var supportedCache = null;

  function isSupported() {
    if (supportedCache === null) {
      try {
        var c = document.createElement('canvas');
        supportedCache = !!(c.getContext('webgl') || c.getContext('experimental-webgl'));
      } catch (e) {
        supportedCache = false;
      }
    }
    return supportedCache;
  }

  function isActive() {
    return !!iframe;
  }

  function clearReadyWatch() {
    if (readyListener) {
      window.removeEventListener('message', readyListener);
      readyListener = null;
    }
    if (readyTimer) {
      clearTimeout(readyTimer);
      readyTimer = null;
    }
  }

  function fail(frame, onFail) {
    clearReadyWatch();
    if (frame) {
      try { frame.remove(); } catch (e) { /* ignore */ }
    }
    if (iframe === frame) iframe = null;
    if (onFail) {
      try { onFail(); } catch (e) { /* ignore */ }
    }
  }

  function setMode(mode) {
    if (!iframe || !iframe.contentWindow) return;
    try {
      iframe.contentWindow.postMessage({ type: 'oceanMode', mode: mode }, '*');
    } catch (e) { /* ignore */ }
  }

  function mount(parentEl, mode, onFail) {
    if (!isSupported()) {
      if (onFail) onFail();
      return false;
    }
    if (iframe) {
      setMode(mode);
      return true;
    }

    var anchor = document.getElementById('oceanfield');
    iframe = document.createElement('iframe');
    iframe.id = 'ocean3dFrame';
    iframe.src = './themes/ocean/webgl.html?fps=60';
    iframe.setAttribute('frameborder', '0');
    iframe.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;' +
      'z-index:0;pointer-events:none;border:0;opacity:0;transition:opacity 0.8s ease;';

    var currentFrame = iframe;
    readyListener = function (e) {
      if (!currentFrame.contentWindow || e.source !== currentFrame.contentWindow) return;
      var d = e.data;
      if (d && d.type === 'oceanReady') {
        clearReadyWatch();
        currentFrame.style.opacity = '1';
        setMode(mode);
      } else if (d && d.type === 'oceanError') {
        fail(currentFrame, onFail);
      }
    };
    window.addEventListener('message', readyListener);
    readyTimer = setTimeout(function () {
      fail(currentFrame, onFail);
    }, 12000);

    var host = (anchor && anchor.parentElement) ? anchor.parentElement : (parentEl || document.body);
    host.insertBefore(iframe, anchor ? anchor.nextSibling : null);
    return true;
  }

  function unmount() {
    clearReadyWatch();
    if (!iframe) return;
    try {
      if (iframe.contentWindow && iframe.contentWindow.__ocean) {
        iframe.contentWindow.__ocean.cleanup();
      }
    } catch (e) { /* ignore */ }
    try { iframe.remove(); } catch (e) { /* ignore */ }
    iframe = null;
  }

  window.OceanWallpaper3D = {
    isSupported: isSupported,
    isActive: isActive,
    mount: mount,
    unmount: unmount,
    setMode: setMode
  };
})();
