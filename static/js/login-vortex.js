/**
 * 登录页左侧：沿原图已有螺旋纹理中心缓慢旋转，不额外造涡。
 */
(function () {
  var visual = document.querySelector(".login-emo-visual");
  var canvas = document.getElementById("loginVortexCanvas");
  var img = document.getElementById("loginPhotoSrc");
  if (!visual || !canvas || !img) return;

  var ctx = canvas.getContext("2d", { alpha: false });
  var reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var running = false;
  var rafId = 0;
  var startTime = 0;

  var TWIST_SCALE = 0.45;
  var CORE_SPEED = 0.106;

  /**
   * cx/cy/r：对齐红标与原图螺旋视觉中心（归一化 0-1）
   * range：有效范围占 r 的比例，与图中螺旋 footprint 一致
   * dir：1=顺时针 -1=逆时针（按红标箭头）
   */
  var VORTICES = [
    { cx: 0.14, cy: 0.11, r: 0.13, range: 0.94, dir: 1, speed: 0.10, large: true },
    { cx: 0.50, cy: 0.10, r: 0.075, range: 0.90, dir: -1, speed: 0.10, large: true },
    { cx: 0.84, cy: 0.11, r: 0.10, range: 0.92, dir: 1, speed: 0.10, large: true },
    { cx: 0.08, cy: 0.41, r: 0.065, range: 0.88, dir: -1, speed: 0.094, core: true },
    { cx: 0.48, cy: 0.35, r: 0.14, range: 0.95, dir: -1, speed: 0.10, large: true, core: true },
    { cx: 0.71, cy: 0.37, r: 0.088, range: 0.90, dir: -1, speed: 0.10, large: true, core: true },
  ];

  var layout = { w: 0, h: 0, dx: 0, dy: 0, dw: 0, dh: 0 };
  var srcBuffer = null;

  function coverRect(cw, ch, iw, ih) {
    var ir = iw / ih;
    var cr = cw / ch;
    var dw, dh, dx, dy;
    if (ir > cr) {
      dh = ch;
      dw = ch * ir;
      dx = (cw - dw) * 0.5;
      dy = ch * 0.42 - dh * 0.42;
    } else {
      dw = cw;
      dh = cw / ir;
      dx = (cw - dw) * 0.5;
      dy = ch * 0.42 - dh * 0.42;
    }
    return { dx: dx, dy: dy, dw: dw, dh: dh };
  }

  function isRoadZone(nx, ny) {
    if (ny < 0.50) return false;
    var t = (ny - 0.50) / 0.48;
    var halfW = 0.075 + t * 0.21;
    var centerX = 0.50 - t * 0.03;
    return Math.abs(nx - centerX) < halfW;
  }

  function isGrassZone(nx, ny) {
    if (ny >= 0.66 && nx < 0.24) return true;
    if (ny >= 0.64 && nx > 0.86) return true;
    return false;
  }

  function isStableZone(nx, ny) {
    return isRoadZone(nx, ny) || isGrassZone(nx, ny);
  }

  function outerRadius(v) {
    return v.r * (v.range != null ? v.range : 0.85);
  }

  function rebuildSourceBuffer() {
    if (!img.naturalWidth) return;
    var rect = coverRect(layout.w, layout.h, img.naturalWidth, img.naturalHeight);
    layout.dx = rect.dx;
    layout.dy = rect.dy;
    layout.dw = rect.dw;
    layout.dh = rect.dh;
    var off = document.createElement("canvas");
    off.width = layout.w;
    off.height = layout.h;
    var octx = off.getContext("2d", { alpha: false });
    octx.fillStyle = "#dce8e0";
    octx.fillRect(0, 0, layout.w, layout.h);
    octx.drawImage(img, layout.dx, layout.dy, layout.dw, layout.dh);
    srcBuffer = octx.getImageData(0, 0, layout.w, layout.h);
  }

  function sampleBilinear(data, w, h, x, y) {
    if (x < 0 || y < 0 || x >= w - 1 || y >= h - 1) return null;
    var x0 = x | 0;
    var y0 = y | 0;
    var fx = x - x0;
    var fy = y - y0;
    var i00 = (y0 * w + x0) * 4;
    var i10 = i00 + 4;
    var i01 = i00 + w * 4;
    var i11 = i01 + 4;
    return [
      data[i00] * (1 - fx) * (1 - fy) + data[i10] * fx * (1 - fy) + data[i01] * (1 - fx) * fy + data[i11] * fx * fy,
      data[i00 + 1] * (1 - fx) * (1 - fy) + data[i10 + 1] * fx * (1 - fy) + data[i01 + 1] * (1 - fx) * fy + data[i11 + 1] * fx * fy,
      data[i00 + 2] * (1 - fx) * (1 - fy) + data[i10 + 2] * fx * (1 - fy) + data[i01 + 2] * (1 - fx) * fy + data[i11 + 2] * fx * fy,
    ];
  }

  function softFalloff(dist, v) {
    var outer = outerRadius(v);
    if (dist >= outer) return 0;
    var inner = outer * 0.42;
    if (dist <= inner) return 1;
    var t = 1 - (dist - inner) / (outer - inner);
    return t * t * (3 - 2 * t);
  }

  function twistRamp(dist, outer, soft) {
    var ring = dist / outer;
    var core = 1 - ring;
    return (0.12 + 0.88 * core * core) * soft;
  }

  function findVortex(nx, ny) {
    var best = null;
    var bestSoft = 0;
    for (var i = 0; i < VORTICES.length; i++) {
      var v = VORTICES[i];
      var ddx = nx - v.cx;
      var ddy = ny - v.cy;
      var dist = Math.sqrt(ddx * ddx + ddy * ddy);
      var soft = softFalloff(dist, v);
      if (soft > bestSoft) {
        bestSoft = soft;
        best = { v: v, dist: dist, soft: soft };
      }
    }
    if (!best || bestSoft < 0.04) return null;
    return best;
  }

  function renderFrame(timeMs) {
    if (!srcBuffer) return;
    var t = (timeMs - startTime) * 0.001;
    var w = layout.w;
    var h = layout.h;
    var src = srcBuffer.data;
    var out = new Uint8ClampedArray(src);
    var dx = layout.dx;
    var dy = layout.dy;
    var dw = layout.dw;
    var dh = layout.dh;
    var scale = Math.min(dw, dh);

    var y0 = Math.max(0, Math.floor(dy));
    var y1 = Math.min(h - 1, Math.ceil(dy + dh));
    var x0 = Math.max(0, Math.floor(dx));
    var x1 = Math.min(w - 1, Math.ceil(dx + dw));

    for (var py = y0; py <= y1; py++) {
      for (var px = x0; px <= x1; px++) {
        var ix = (px - dx) / dw;
        var iy = (py - dy) / dh;
        if (ix < 0 || ix > 1 || iy < 0 || iy > 1) continue;
        if (isStableZone(ix, iy)) continue;

        var hit = findVortex(ix, iy);
        if (!hit) continue;

        var v = hit.v;
        var outer = outerRadius(v);
        if (hit.dist >= outer) continue;

        var vcx = dx + v.cx * dw;
        var vcy = dy + v.cy * dh;
        var relX = px - vcx;
        var relY = py - vcy;
        var r = Math.sqrt(relX * relX + relY * relY);
        var maxR = outer * scale;
        if (r < 0.5 || r > maxR) continue;

        var spd = v.core ? CORE_SPEED : v.speed;
        var ramp = twistRamp(hit.dist, outer, hit.soft);
        var twist = t * spd * v.dir * ramp * TWIST_SCALE;

        var angle = Math.atan2(relY, relX);
        var sx = vcx + Math.cos(angle - twist) * r;
        var sy = vcy + Math.sin(angle - twist) * r;
        var col = sampleBilinear(src, w, h, sx, sy);
        if (!col) continue;

        var di = (py * w + px) * 4;
        var mix = hit.soft > 0.5 ? 1 : hit.soft * 2.0;
        out[di] = src[di] * (1 - mix) + col[0] * mix;
        out[di + 1] = src[di + 1] * (1 - mix) + col[1] * mix;
        out[di + 2] = src[di + 2] * (1 - mix) + col[2] * mix;
      }
    }

    ctx.putImageData(new ImageData(out, w, h), 0, 0);
  }

  function resize() {
    var rect = visual.getBoundingClientRect();
    var w = Math.max(1, Math.round(rect.width));
    var h = Math.max(1, Math.round(rect.height));
    var dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    var cw = Math.round(w * dpr);
    var ch = Math.round(h * dpr);
    layout.w = cw;
    layout.h = ch;
    canvas.width = cw;
    canvas.height = ch;
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";
    rebuildSourceBuffer();
    if (reducedMotion) drawStatic();
    else renderFrame(performance.now());
  }

  function drawStatic() {
    if (!srcBuffer) rebuildSourceBuffer();
    if (srcBuffer) ctx.putImageData(srcBuffer, 0, 0);
  }

  function tick(now) {
    if (!running) return;
    renderFrame(now);
    rafId = requestAnimationFrame(tick);
  }

  function start() {
    resize();
    if (reducedMotion) return;
    running = true;
    startTime = performance.now();
    rafId = requestAnimationFrame(tick);
  }

  function stop() {
    running = false;
    if (rafId) cancelAnimationFrame(rafId);
  }

  if (img.complete && img.naturalWidth) start();
  else img.addEventListener("load", start);

  if (typeof ResizeObserver !== "undefined") {
    new ResizeObserver(function () { resize(); }).observe(visual);
  } else {
    window.addEventListener("resize", resize);
  }

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) stop();
    else if (!reducedMotion) {
      running = true;
      startTime = performance.now();
      rafId = requestAnimationFrame(tick);
    }
  });
})();
