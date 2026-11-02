// ★ v4.6.2: QWebChannel 初始化（pybridge 主通道）
// 打通 JS→Python：pybridge.runMiemieAgent（咩咩真流式入口）/ cycleEngine / openSettings /
// getMiemiePixelMap / miemieBleat / runWorktreeActorWorkflow 等全部直调。
// Python→JS 方向维持现有 runJavaScript 推送（miemieOnJson），不重复连接信号，避免 token 双路。
(function () {
  if (typeof QWebChannel === 'undefined' || typeof window.qt === 'undefined' || !window.qt.webChannelTransport) {
    console.warn('[MIMO] QWebChannel 不可用（纯浏览器调试？），pybridge 走 _callPython 回退');
    return;
  }
  new QWebChannel(window.qt.webChannelTransport, function (channel) {
    window.pybridge = channel.objects.pybridge;
    console.log('[MIMO] QWebChannel pybridge 已就绪');
    // 通知页面：桥接可用（供依赖 pybridge 的初始化逻辑补跑）
    if (typeof window.onPybridgeReady === 'function') {
      try { window.onPybridgeReady(); } catch (e) { console.error('[MIMO] onPybridgeReady 异常', e); }
    }
  });
})();