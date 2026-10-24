// Offline prayer time calculation (standard astronomical method, as used by
// PrayTimes.org). Returns local times as fractional hours for a given date.
window.PrayerTimes = (function () {
  var rad = Math.PI / 180;
  function sin(d) { return Math.sin(d * rad); }
  function cos(d) { return Math.cos(d * rad); }
  function tan(d) { return Math.tan(d * rad); }
  function asin(x) { return Math.asin(x) / rad; }
  function acos(x) { return Math.acos(x) / rad; }
  function atan2(y, x) { return Math.atan2(y, x) / rad; }
  function acot(x) { return Math.atan(1 / x) / rad; }
  function fix(a, b) { a = a - b * Math.floor(a / b); return a < 0 ? a + b : a; }

  function julian(year, month, day) {
    if (month <= 2) { year -= 1; month += 12; }
    var A = Math.floor(year / 100);
    var B = 2 - A + Math.floor(A / 4);
    return Math.floor(365.25 * (year + 4716)) + Math.floor(30.6001 * (month + 1)) + day + B - 1524.5;
  }

  function sunPosition(jd) {
    var D = jd - 2451545.0;
    var g = fix(357.529 + 0.98560028 * D, 360);
    var q = fix(280.459 + 0.98564736 * D, 360);
    var L = fix(q + 1.915 * sin(g) + 0.020 * sin(2 * g), 360);
    var e = 23.439 - 0.00000036 * D;
    var RA = atan2(cos(e) * sin(L), cos(L)) / 15;
    return { decl: asin(sin(e) * sin(L)), eqt: q / 15 - fix(RA, 24) };
  }

  function calculate(date, cfg) {
    var lat = cfg.lat, lng = cfg.lng;
    var tz = -date.getTimezoneOffset() / 60;
    var jd = julian(date.getFullYear(), date.getMonth() + 1, date.getDate()) - lng / (15 * 24);

    function midDay(t) { return fix(12 - sunPosition(jd + t).eqt, 24); }
    function angleTime(angle, t, ccw) {
      var decl = sunPosition(jd + t).decl;
      var T = acos((-sin(angle) - sin(decl) * sin(lat)) / (cos(decl) * cos(lat))) / 15;
      return midDay(t) + (ccw ? -T : T);
    }
    function asrTime(factor, t) {
      var decl = sunPosition(jd + t).decl;
      return angleTime(-acot(factor + tan(Math.abs(lat - decl))), t);
    }

    // two passes refine the estimate
    var t = { fajr: 5, sunrise: 6, dhuhr: 12, asr: 13, maghrib: 18, isha: 18 };
    for (var i = 0; i < 2; i++) {
      t = {
        fajr: angleTime(cfg.fajrAngle, t.fajr / 24, true),
        sunrise: angleTime(0.833, t.sunrise / 24, true),
        dhuhr: midDay(t.dhuhr / 24),
        asr: asrTime(cfg.asrFactor, t.asr / 24),
        maghrib: angleTime(0.833, t.maghrib / 24),
        isha: angleTime(cfg.ishaAngle, t.isha / 24)
      };
    }

    var out = {};
    for (var k in t) {
      out[k] = t[k] + tz - lng / 15 + ((cfg.offsets && cfg.offsets[k]) || 0) / 60;
    }
    return out;
  }

  return { calculate: calculate };
})();
