/* Timshel — sygile (reuse z insights-card-redesign.html) + ikony.
   window.mSigil(type,color[,size]) → SVG string; typy: contradiction | shared | emergent.
   window.mIco(name) → 16px ikona liniowa. Port natywny: _SigilView.drawRect_ (Core Graphics). */
(function () {
  var uid = 0;
  function sigil(type, color) {
    color = color || "#D9542A";
    var id = "sg" + (uid++);
    var defs =
      '<defs>' +
        '<radialGradient id="' + id + 'n" cx="50%" cy="50%" r="50%">' +
          '<stop offset="0%" stop-color="' + color + '" stop-opacity=".5"/>' +
          '<stop offset="60%" stop-color="' + color + '" stop-opacity=".08"/>' +
          '<stop offset="100%" stop-color="' + color + '" stop-opacity="0"/>' +
        '</radialGradient>' +
        '<radialGradient id="' + id + 'b" cx="50%" cy="50%" r="50%">' +
          '<stop offset="0%" stop-color="#F4DD8E" stop-opacity=".9"/>' +
          '<stop offset="55%" stop-color="#D6B033" stop-opacity=".3"/>' +
          '<stop offset="100%" stop-color="#D6B033" stop-opacity="0"/>' +
        '</radialGradient>' +
      '</defs>';
    function node(x, y) {
      return '<circle cx="' + x + '" cy="' + y + '" r="7" fill="url(#' + id + 'n)"/>' +
             '<circle cx="' + x + '" cy="' + y + '" r="2.5" fill="#C24010"/>' +
             '<circle cx="' + x + '" cy="' + y + '" r="1" fill="#FAF3E2"/>';
    }
    function bloom(x, y, r) {
      r = r || 3;
      return '<circle cx="' + x + '" cy="' + y + '" r="' + (r * 2.6) + '" fill="url(#' + id + 'b)"/>' +
             '<circle cx="' + x + '" cy="' + y + '" r="' + r + '" fill="#F4DD8E"/>' +
             '<circle cx="' + x + '" cy="' + y + '" r="' + (r * 0.4) + '" fill="#FFFBF0"/>';
    }
    var p = "";
    if (type === "contradiction") {
      p += '<line x1="5" y1="16" x2="27" y2="16" stroke="' + color + '" stroke-opacity=".28" stroke-width="1" stroke-dasharray="2 4"/>';
      p += '<path d="M8 16 Q16 7 24 16" fill="none" stroke="' + color + '" stroke-opacity=".85" stroke-width="1.5" stroke-linecap="round"/>';
      p += '<path d="M8 16 Q16 25 24 16" fill="none" stroke="' + color + '" stroke-opacity=".85" stroke-width="1.5" stroke-linecap="round"/>';
      p += bloom(16, 16, 2.4);
      p += node(8, 16) + node(24, 16);
    } else if (type === "shared") {
      p += '<path d="M9 24 L16 9" fill="none" stroke="' + color + '" stroke-opacity=".7" stroke-width="1.4" stroke-linecap="round"/>';
      p += '<path d="M23 24 L16 9" fill="none" stroke="' + color + '" stroke-opacity=".7" stroke-width="1.4" stroke-linecap="round"/>';
      p += node(9, 24) + node(23, 24);
      p += bloom(16, 9, 3);
    } else {
      var nd = [[8, 9], [25, 12], [15, 26]];
      nd.forEach(function (c) {
        p += '<path d="M16 16 L' + c[0] + ' ' + c[1] + '" fill="none" stroke="' + color + '" stroke-opacity=".55" stroke-width="1.3" stroke-linecap="round"/>';
      });
      nd.forEach(function (c) { p += node(c[0], c[1]); });
      p += bloom(16, 16, 3);
    }
    return '<svg viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg">' + defs + p + '</svg>';
  }

  function ico(name) {
    var i = {
      szukaj: '<circle cx="7" cy="7" r="4.4"/><path d="M10.4 10.4 L14 14"/>',
      mic: '<rect x="5.5" y="1.5" width="5" height="8.4" rx="2.5"/><path d="M2.8 7.8 a5.2 5.2 0 0 0 10.4 0 M8 13 v1.6"/>',
      zadanie: '<rect x="2.5" y="2.5" width="11" height="11" rx="2.6"/><path d="M5.4 8.2l2 2 3.4-3.9"/>',
      kalendarz: '<rect x="2.5" y="3.5" width="11" height="10" rx="1.6"/><path d="M2.5 6.4h11M5.6 2v3M10.4 2v3"/>',
      kopiuj: '<rect x="5" y="5" width="8.5" height="8.5" rx="1.6"/><path d="M10.4 5V3.5A1.4 1.4 0 0 0 9 2.1H3.5A1.4 1.4 0 0 0 2.1 3.5V9a1.4 1.4 0 0 0 1.4 1.4H5"/>',
      caret: '<path d="M4.5 6.5 L8 10 L11.5 6.5"/>',
      wiecej: '<circle cx="3.2" cy="8" r="1.2" fill="currentColor" stroke="none"/><circle cx="8" cy="8" r="1.2" fill="currentColor" stroke="none"/><circle cx="12.8" cy="8" r="1.2" fill="currentColor" stroke="none"/>',
      claude: '<path d="M8 2.2 L10 6 L14 6.6 L11 9.6 L11.8 13.8 L8 11.8 L4.2 13.8 L5 9.6 L2 6.6 L6 6 Z" fill="currentColor" stroke="none" opacity=".9"/>'
    };
    return '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round">' + i[name] + '</svg>';
  }

  window.mSigil = sigil;
  window.mIco = ico;

  /* auto-mount: <span data-sigil="shared" data-color="#D6B033" data-size="30"></span>
                 <span data-ico="zadanie"></span> */
  window.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-sigil]").forEach(function (el) {
      var s = el.getAttribute("data-size") || "30";
      el.innerHTML = sigil(el.getAttribute("data-sigil"), el.getAttribute("data-color") || undefined);
      var svg = el.firstChild;
      svg.setAttribute("width", s); svg.setAttribute("height", s);
      svg.style.display = "block"; svg.style.overflow = "visible";
    });
    document.querySelectorAll("[data-ico]").forEach(function (el) {
      el.innerHTML = ico(el.getAttribute("data-ico"));
      el.style.display = "inline-grid"; el.style.placeItems = "center";
    });
  });
})();
