// Rotating background photos: local files first, then Wikimedia Commons
// nature photos fetched by the TV, then the bundled fallback image.
window.Backgrounds = (function () {
  var CACHE_KEY = "bgPhotos.v1";
  var CACHE_DAYS = 7;
  var layers, current = 0, photos = [], index = 0;

  function shuffle(a) {
    for (var i = a.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var t = a[i]; a[i] = a[j]; a[j] = t;
    }
    return a;
  }

  function stripHtml(s) {
    var d = document.createElement("div");
    d.innerHTML = s || "";
    return (d.textContent || "").replace(/\s+/g, " ").trim();
  }

  function readCache() {
    try {
      var c = JSON.parse(localStorage.getItem(CACHE_KEY));
      if (c && Date.now() - c.time < CACHE_DAYS * 86400000 && c.photos.length) return c.photos;
    } catch (e) { /* ignore */ }
    return null;
  }

  function writeCache(list) {
    try { localStorage.setItem(CACHE_KEY, JSON.stringify({ time: Date.now(), photos: list })); } catch (e) { /* ignore */ }
  }

  function fetchCategory(cat) {
    var url = "https://commons.wikimedia.org/w/api.php?action=query&format=json&origin=*" +
      "&generator=categorymembers&gcmtype=file&gcmlimit=60&gcmtitle=" + encodeURIComponent(cat) +
      "&prop=imageinfo&iiprop=url|size|extmetadata&iiurlwidth=1920" +
      "&iiextmetadatafilter=Artist|LicenseShortName";
    return fetch(url).then(function (r) { return r.json(); }).then(function (data) {
      var pages = (data.query && data.query.pages) || {};
      var out = [];
      for (var k in pages) {
        var info = pages[k].imageinfo && pages[k].imageinfo[0];
        // landscape photos only, large enough for a TV
        if (!info || !info.thumburl || info.width < info.height * 1.3 || info.width < 1600) continue;
        var meta = info.extmetadata || {};
        out.push({
          url: info.thumburl,
          credit: "Photo: " + stripHtml(meta.Artist && meta.Artist.value) +
            (meta.LicenseShortName ? " / " + meta.LicenseShortName.value : "") + " / Wikimedia Commons"
        });
      }
      return out;
    }).catch(function () { return []; });
  }

  function show(photo) {
    var img = new Image();
    img.onload = function () {
      var next = layers[1 - current];
      next.style.backgroundImage = "url('" + photo.url + "')";
      next.classList.add("visible");
      layers[current].classList.remove("visible");
      current = 1 - current;
      document.getElementById("credit").textContent = photo.credit || "";
    };
    img.onerror = function () {
      // skip broken photos
      photos.splice(photos.indexOf(photo), 1);
      if (photos.length) advance();
    };
    img.src = photo.url;
  }

  function advance() {
    if (!photos.length) return;
    index = (index + 1) % photos.length;
    show(photos[index]);
  }

  function start(cfg) {
    layers = [document.getElementById("bgA"), document.getElementById("bgB")];
    var fallback = { url: cfg.fallback, credit: "" };
    photos = [fallback];
    show(fallback);

    var local = (cfg.local || []).map(function (f) { return { url: "backgrounds/" + f, credit: "" }; });
    if (local.length) {
      photos = shuffle(local);
      show(photos[0]);
    } else if (cfg.online) {
      var cached = readCache();
      if (cached) {
        photos = shuffle(cached);
        show(photos[0]);
      } else {
        Promise.all(cfg.categories.map(fetchCategory)).then(function (lists) {
          var all = [].concat.apply([], lists);
          if (!all.length) return; // offline: keep the fallback
          writeCache(all);
          photos = shuffle(all);
          index = 0;
          show(photos[0]);
        });
      }
    }
    setInterval(advance, (cfg.changeEverySeconds || 90) * 1000);
  }

  return { start: start, next: advance };
})();
