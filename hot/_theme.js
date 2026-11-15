(function (g) {
  "use strict";
  var TKEY = "hotradar.theme";
  function getStorage(owner) {
    try { return owner && owner.localStorage; } catch (e) {}
  }
  function readTheme(storage) {
    try {
      if (!storage) return "dark";
      var th = storage.getItem(TKEY);
      if (th === "dark" || th === "light") return th;
    } catch (e) {}
    return "dark";
  }
  function applyTheme(el, storage) {
    var t = readTheme(storage);
    try { el.setAttribute("data-theme", t); } catch (e) {}
    return t;
  }
  function toggleTheme(el, storage) {
    var cur = "dark";
    try { cur = el.getAttribute("data-theme") === "light" ? "light" : "dark"; } catch (e) {}
    var next = cur === "dark" ? "light" : "dark";
    try { el.setAttribute("data-theme", next); } catch (e) {}
    try { if (storage) storage.setItem(TKEY, next); } catch (e) {}
    return next;
  }
  g.hotradarTheme = { TKEY: TKEY, getStorage: getStorage, readTheme: readTheme, applyTheme: applyTheme, toggleTheme: toggleTheme };
  if (typeof document !== "undefined") {
    try {
      applyTheme(document.documentElement, getStorage(g));
    } catch (e) {
      try { document.documentElement.setAttribute("data-theme", "dark"); } catch (e2) {}
    }
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
