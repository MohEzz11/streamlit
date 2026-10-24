(function () {
  var cfg = window.HOME_CONFIG;
  var KEY = { LEFT: 37, UP: 38, RIGHT: 39, DOWN: 40, ENTER: 13, BACK: 461 };
  var TILE_STEP = 416; // tile width + gap, keep in sync with style.css
  var VISIBLE_TILES = 4;
  var ICONS = {
    input: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 7h16v6a6 6 0 0 1-6 6h-4a6 6 0 0 1-6-6z"/></svg>',
    wifi: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 9a15 15 0 0 1 20 0M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0"/><circle cx="12" cy="19.5" r="1"/></svg>',
    gear: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/></svg>'
  };
  var PRAYERS = [
    { key: "fajr", en: "Fajr", ar: "الفجر" },
    { key: "sunrise", en: "Sunrise", ar: "الشروق", minor: true },
    { key: "dhuhr", en: "Dhuhr", ar: "الظهر" },
    { key: "asr", en: "Asr", ar: "العصر" },
    { key: "maghrib", en: "Maghrib", ar: "المغرب" },
    { key: "isha", en: "Isha", ar: "العشاء" }
  ];

  var rows = [];        // rows actually shown (config rows + optional all-apps row)
  var launchPoints = []; // apps installed on the TV, when the TV allows listing them
  var focus = { zone: "rows", row: 0, col: 0 };
  var lastRowCol = 0;
  var bridges = [];      // keep service bridges referenced until they answer

  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }

  // ---------- TV services ----------
  function luna(uri, params, cb) {
    if (typeof window.PalmServiceBridge === "undefined") { if (cb) cb(null); return; }
    var bridge = new window.PalmServiceBridge();
    bridges.push(bridge);
    bridge.onservicecallback = function (msg) {
      bridges.splice(bridges.indexOf(bridge), 1);
      var res = null;
      try { res = JSON.parse(msg); } catch (e) { /* ignore */ }
      if (cb) cb(res);
    };
    bridge.call(uri, JSON.stringify(params || {}));
  }

  function findApp(tile) {
    if (!launchPoints.length) return null;
    var i, lp;
    if (tile.id) {
      for (i = 0; i < launchPoints.length; i++) if (launchPoints[i].id === tile.id) return launchPoints[i];
    }
    if (tile.match) {
      var m = tile.match.toLowerCase();
      for (i = 0; i < launchPoints.length; i++) {
        lp = launchPoints[i];
        if ((lp.title || "").toLowerCase().indexOf(m) !== -1 || (lp.id || "").toLowerCase().indexOf(m.replace(/\s/g, "")) !== -1) return lp;
      }
    }
    return null;
  }

  function buildRows() {
    rows = cfg.rows.map(function (row) {
      return {
        title: row.title,
        tiles: row.tiles.map(function (t) {
          var lp = findApp(t);
          var tile = { name: t.name, color: t.color, text: t.text, id: lp ? lp.id : t.id, params: t.params, icon: lp && (lp.largeIcon || lp.icon) };
          // when the TV lists its apps, hide tiles for apps that are not installed
          tile.missing = launchPoints.length > 0 && !lp;
          return tile;
        }).filter(function (t) { return !t.missing; })
      };
    }).filter(function (r) { return r.tiles.length; });

    if (cfg.showAllApps && launchPoints.length) {
      rows.push({
        title: "All Apps",
        tiles: launchPoints.filter(function (lp) { return lp.id !== "com.mohezz.homescreen" && lp.title; }).map(function (lp) {
          return { name: lp.title, id: lp.id, params: lp.params, icon: lp.largeIcon || lp.icon, color: lp.bgColor || "#1e2a22", text: "#ffffff" };
        })
      });
    }
    if (!rows.length) rows = [{ title: "Apps", tiles: [{ name: "Settings", id: "com.palm.app.settings", color: "#333", text: "#fff" }] }];
  }

  // ---------- render ----------
  function render() {
    $("pills").innerHTML = cfg.pills.map(function (p, i) {
      return '<div class="pill" data-i="' + i + '">' + (ICONS[p.icon] || "") + "<span>" + esc(p.label) + "</span></div>";
    }).join("");

    $("rows").innerHTML = rows.map(function (row, r) {
      return '<section class="row" data-r="' + r + '"><h2 class="row-title"></h2><div class="tiles"><div class="track">' +
        row.tiles.map(function (t, c) {
          var inner = t.icon
            ? '<img src="' + esc(t.icon) + '" onerror="this.parentNode.classList.remove(\'has-icon\');this.remove()"><span>' + esc(t.name) + "</span>"
            : "<span>" + esc(t.name) + "</span>";
          return '<div class="tile' + (t.icon ? " has-icon" : "") + '" data-r="' + r + '" data-c="' + c + '" style="background:' + t.color + ";color:" + t.text + '">' + inner + "</div>";
        }).join("") + "</div></div></section>";
    }).join("");
    focus.row = Math.min(focus.row, rows.length - 1);
    focus.col = Math.min(focus.col, rows[focus.row].tiles.length - 1);
  }

  // ---------- clock + prayer ----------
  function fmt(hours) {
    var mins = Math.round(hours * 60);
    mins = ((mins % 1440) + 1440) % 1440;
    var h = Math.floor(mins / 60), m = mins % 60;
    return (h % 12 || 12) + ":" + ("0" + m).slice(-2);
  }

  var lastAlert = "";
  function tickPrayer(now) {
    var times = window.PrayerTimes.calculate(now, cfg.prayer);
    var nowH = now.getHours() + now.getMinutes() / 60 + now.getSeconds() / 3600;
    var next = null;
    for (var i = 0; i < PRAYERS.length; i++) {
      if (!PRAYERS[i].minor && times[PRAYERS[i].key] > nowH) { next = PRAYERS[i]; break; }
    }
    var nextAt = next ? times[next.key] : null;
    if (!next) { // after Isha: tomorrow's Fajr
      next = PRAYERS[0];
      var tomorrow = new Date(now.getTime() + 86400000);
      nextAt = window.PrayerTimes.calculate(tomorrow, cfg.prayer).fajr + 24;
    }

    $("prayers").innerHTML = PRAYERS.map(function (p) {
      return '<div class="prayer' + (p === next ? " next" : "") + (p.minor ? " minor" : "") + '">' +
        '<div class="p-name">' + p.en + ' <span class="p-ar">' + p.ar + "</span></div>" +
        '<div class="p-time">' + fmt(times[p.key]) + "</div></div>";
    }).join("");

    var left = Math.max(0, Math.round((nextAt - nowH) * 60));
    $("next-prayer").textContent = next.en + " in " + (left >= 60 ? Math.floor(left / 60) + "h " : "") + (left % 60) + "m";

    // gentle reminder when a prayer time arrives
    for (var j = 0; j < PRAYERS.length; j++) {
      var p = PRAYERS[j], diff = (nowH - times[p.key]) * 60;
      var tag = now.toDateString() + p.key;
      if (!p.minor && diff >= 0 && diff < 1 && lastAlert !== tag) {
        lastAlert = tag;
        toast("It is time for " + p.en + " prayer  " + p.ar, 15000);
      }
    }
  }

  function tick() {
    var now = new Date();
    var h = now.getHours();
    var days = ["SUNDAY", "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"];
    var months = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"];
    $("greeting").textContent = h < 12 ? "GOOD MORNING" : h < 18 ? "GOOD AFTERNOON" : "GOOD EVENING";
    $("time").textContent = (h % 12 || 12) + ":" + ("0" + now.getMinutes()).slice(-2);
    $("ampm").textContent = h < 12 ? "AM" : "PM";
    $("date").textContent = days[now.getDay()] + " " + now.getDate() + " " + months[now.getMonth()];
    tickPrayer(now);
  }

  // ---------- focus ----------
  function glowFor(tile) {
    var hex = (tile.color || "#2e6b3a").replace("#", "");
    if (hex.length !== 6) return "#2e6b3a";
    var lum = (parseInt(hex.substr(0, 2), 16) * 299 + parseInt(hex.substr(2, 2), 16) * 587 + parseInt(hex.substr(4, 2), 16) * 114) / 1000;
    return lum > 180 ? tile.text : tile.color;
  }

  function applyFocus() {
    var els = document.querySelectorAll(".focused");
    for (var i = 0; i < els.length; i++) els[i].classList.remove("focused");

    var sections = document.querySelectorAll(".row");
    for (var r = 0; r < sections.length; r++) {
      var active = r === focus.row;
      sections[r].classList.toggle("active", active);
      sections[r].querySelector(".row-title").textContent = active && focus.zone === "rows"
        ? rows[r].tiles[focus.col].name
        : rows[r].title;
    }

    if (focus.zone === "pills") {
      document.querySelector('.pill[data-i="' + focus.col + '"]').classList.add("focused");
      return;
    }
    var tile = rows[focus.row].tiles[focus.col];
    document.querySelector('.tile[data-r="' + focus.row + '"][data-c="' + focus.col + '"]').classList.add("focused");
    $("glow").style.background = "radial-gradient(ellipse 60% 70% at 25% 40%, " + glowFor(tile) + " 0%, transparent 70%)";
    var section = document.querySelector('.row[data-r="' + focus.row + '"]');
    $("rows").style.transform = "translateY(" + (-section.offsetTop) + "px)";
    var shift = Math.max(0, Math.min(focus.col - (VISIBLE_TILES - 1), rows[focus.row].tiles.length - VISIBLE_TILES));
    section.querySelector(".track").style.transform = "translateX(" + (-Math.max(0, shift) * TILE_STEP) + "px)";
  }

  function move(key) {
    if (focus.zone === "pills") {
      if (key === KEY.LEFT) focus.col = Math.max(0, focus.col - 1);
      if (key === KEY.RIGHT) focus.col = Math.min(cfg.pills.length - 1, focus.col + 1);
      if (key === KEY.DOWN) focus = { zone: "rows", row: 0, col: lastRowCol };
    } else {
      var count = rows[focus.row].tiles.length;
      if (key === KEY.LEFT) focus.col = Math.max(0, focus.col - 1);
      if (key === KEY.RIGHT) focus.col = Math.min(count - 1, focus.col + 1);
      if (key === KEY.UP) {
        if (focus.row === 0) { lastRowCol = focus.col; focus = { zone: "pills", row: 0, col: cfg.pills.length - 1 }; }
        else focus.row--;
      }
      if (key === KEY.DOWN && focus.row < rows.length - 1) focus.row++;
      if (focus.zone === "rows") focus.col = Math.min(focus.col, rows[focus.row].tiles.length - 1);
    }
    applyFocus();
  }

  // ---------- launching ----------
  function toast(msg, ms) {
    var t = $("toast");
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(function () { t.classList.remove("show"); }, ms || 2500);
  }

  function launch(item) {
    var name = item.name || item.label;
    if (typeof window.PalmServiceBridge === "undefined") { toast("Preview mode: would open " + name); return; }
    if (!item.id) { toast(name + " not found. Add its app ID in config.js", 5000); return; }
    var params = { id: item.id };
    if (item.params) params.params = item.params;
    luna("luna://com.webos.applicationManager/launch", params, function (res) {
      if (res && res.returnValue === false) toast(name + " is not installed on this TV");
    });
  }

  function activate() {
    if (focus.zone === "pills") launch(cfg.pills[focus.col]);
    else launch(rows[focus.row].tiles[focus.col]);
  }

  // ---------- input ----------
  document.addEventListener("keydown", function (e) {
    var k = e.keyCode;
    if (k === KEY.ENTER) { activate(); e.preventDefault(); return; }
    if (k === KEY.BACK) {
      focus = { zone: "rows", row: 0, col: 0 };
      applyFocus();
      e.preventDefault();
      return;
    }
    if (k >= 37 && k <= 40) { move(k); e.preventDefault(); }
  });

  // Magic Remote pointer support
  document.addEventListener("mouseover", function (e) {
    var el = e.target.closest(".tile, .pill");
    if (!el) return;
    if (el.classList.contains("pill")) focus = { zone: "pills", row: 0, col: +el.dataset.i };
    else focus = { zone: "rows", row: +el.dataset.r, col: +el.dataset.c };
    applyFocus();
  });
  document.addEventListener("click", function (e) {
    if (e.target.closest(".tile, .pill")) activate();
  });

  function refresh() {
    buildRows();
    render();
    applyFocus();
  }

  // ---------- start ----------
  refresh();
  tick();
  setInterval(tick, 10000);
  window.Backgrounds.start(cfg.backgrounds);

  // Ask the TV for its installed apps; if allowed, tiles get real icons,
  // names are matched, and the All Apps row appears.
  luna("luna://com.webos.applicationManager/listLaunchPoints", {}, function (res) {
    if (res && res.launchPoints && res.launchPoints.length) {
      launchPoints = res.launchPoints;
      refresh();
    }
  });
})();
