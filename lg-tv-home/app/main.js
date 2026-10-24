(function () {
  var cfg = window.HOME_CONFIG;
  var KEY = { LEFT: 37, UP: 38, RIGHT: 39, DOWN: 40, ENTER: 13, BACK: 461 };
  var ICONS = {
    input: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 7h16v6a6 6 0 0 1-6 6h-4a6 6 0 0 1-6-6z"/></svg>',
    wifi: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 9a15 15 0 0 1 20 0M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0"/><circle cx="12" cy="19.5" r="1"/></svg>',
    gear: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/></svg>'
  };

  // focus: zone "pills" uses col only; zone "rows" uses row + col
  var focus = { zone: "rows", row: 0, col: 0 };
  var lastRowCol = 0;

  function $(id) { return document.getElementById(id); }

  // ---------- render ----------
  function render() {
    $("pills").innerHTML = cfg.pills.map(function (p, i) {
      return '<div class="pill" data-i="' + i + '">' + (ICONS[p.icon] || "") + "<span>" + p.label + "</span></div>";
    }).join("");

    $("rows").innerHTML = cfg.rows.map(function (row, r) {
      return '<section class="row" data-r="' + r + '"><h2 class="row-title"></h2><div class="tiles">' +
        row.tiles.map(function (t, c) {
          return '<div class="tile" data-r="' + r + '" data-c="' + c + '" style="background:' + t.color + ";color:" + t.text + '">' + t.name + "</div>";
        }).join("") + "</div></section>";
    }).join("");
  }

  // ---------- clock ----------
  function tick() {
    var now = new Date();
    var h = now.getHours();
    var greeting = h < 12 ? "GOOD MORNING" : h < 18 ? "GOOD AFTERNOON" : "GOOD EVENING";
    var h12 = h % 12 || 12;
    var m = ("0" + now.getMinutes()).slice(-2);
    var days = ["SUNDAY", "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"];
    var months = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"];
    $("greeting").textContent = greeting;
    $("time").textContent = h12 + ":" + m;
    $("ampm").textContent = h < 12 ? "AM" : "PM";
    $("date").textContent = days[now.getDay()] + " " + now.getDate() + " " + months[now.getMonth()];
  }

  // ---------- focus ----------
  function glowFor(tile) {
    // light tiles (e.g. YouTube) glow with their text colour instead
    var hex = tile.color.replace("#", "");
    var lum = (parseInt(hex.substr(0, 2), 16) * 299 + parseInt(hex.substr(2, 2), 16) * 587 + parseInt(hex.substr(4, 2), 16) * 114) / 1000;
    return lum > 180 ? tile.text : tile.color;
  }

  function applyFocus() {
    var els = document.querySelectorAll(".focused");
    for (var i = 0; i < els.length; i++) els[i].classList.remove("focused");

    var rows = document.querySelectorAll(".row");
    for (var r = 0; r < rows.length; r++) {
      var active = r === focus.row;
      rows[r].classList.toggle("active", active);
      rows[r].querySelector(".row-title").textContent = active && focus.zone === "rows"
        ? cfg.rows[r].tiles[focus.col].name
        : cfg.rows[r].title;
    }

    if (focus.zone === "pills") {
      document.querySelector('.pill[data-i="' + focus.col + '"]').classList.add("focused");
    } else {
      var tile = cfg.rows[focus.row].tiles[focus.col];
      document.querySelector('.tile[data-r="' + focus.row + '"][data-c="' + focus.col + '"]').classList.add("focused");
      $("glow").style.background = "radial-gradient(ellipse 60% 70% at 25% 35%, " + glowFor(tile) + " 0%, transparent 70%)";
      $("rows").style.transform = "translateY(" + (-document.querySelector(".row[data-r=\"" + focus.row + "\"]").offsetTop) + "px)";
    }
  }

  function move(key) {
    if (focus.zone === "pills") {
      if (key === KEY.LEFT) focus.col = Math.max(0, focus.col - 1);
      if (key === KEY.RIGHT) focus.col = Math.min(cfg.pills.length - 1, focus.col + 1);
      if (key === KEY.DOWN) { focus = { zone: "rows", row: 0, col: lastRowCol }; }
    } else {
      var count = cfg.rows[focus.row].tiles.length;
      if (key === KEY.LEFT) focus.col = Math.max(0, focus.col - 1);
      if (key === KEY.RIGHT) focus.col = Math.min(count - 1, focus.col + 1);
      if (key === KEY.UP) {
        if (focus.row === 0) { lastRowCol = focus.col; focus = { zone: "pills", row: 0, col: cfg.pills.length - 1 }; }
        else focus.row--;
      }
      if (key === KEY.DOWN && focus.row < cfg.rows.length - 1) focus.row++;
      if (focus.zone === "rows") {
        focus.col = Math.min(focus.col, cfg.rows[focus.row].tiles.length - 1);
      }
    }
    applyFocus();
  }

  // ---------- launching ----------
  function toast(msg) {
    var t = $("toast");
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(function () { t.classList.remove("show"); }, 2500);
  }

  function launch(item) {
    var params = { id: item.id };
    if (item.params) params.params = item.params;

    if (typeof window.PalmServiceBridge === "undefined") {
      toast("Preview mode: would open " + (item.name || item.label));
      return;
    }
    var bridge = new window.PalmServiceBridge();
    bridge.onservicecallback = function (msg) {
      try {
        var res = JSON.parse(msg);
        if (res.returnValue === false) toast((item.name || item.label) + " is not installed (" + item.id + ")");
      } catch (e) { /* ignore */ }
    };
    bridge.call("luna://com.webos.applicationManager/launch", JSON.stringify(params));
  }

  function activate() {
    if (focus.zone === "pills") launch(cfg.pills[focus.col]);
    else launch(cfg.rows[focus.row].tiles[focus.col]);
  }

  // ---------- input ----------
  document.addEventListener("keydown", function (e) {
    var k = e.keyCode;
    if (k === KEY.ENTER) { activate(); e.preventDefault(); return; }
    if (k === KEY.BACK) {
      // Back returns to the first tile instead of closing the app
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

  render();
  tick();
  setInterval(tick, 10000);
  applyFocus();
})();
