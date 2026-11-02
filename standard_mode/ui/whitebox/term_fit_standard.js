(function() {
  window.TermFitStandard = {
    fit: function(terminal, container) {
      if (!terminal || !container) return;
      var fontSize = parseInt(terminal.options.fontSize) || 14;
      var cellWidth = fontSize * 0.6;
      var cellHeight = fontSize * 1.2;
      var cols = Math.floor(container.clientWidth / cellWidth);
      var rows = Math.floor(container.clientHeight / cellHeight);
      if (cols > 0 && rows > 0) {
        terminal.resize(cols, rows);
      }
    },
    onFontsReady: function(callback) {
      if (document.fonts && document.fonts.ready) {
        document.fonts.ready.then(callback);
      } else {
        setTimeout(callback, 500);
      }
    }
  };
})();
