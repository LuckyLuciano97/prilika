/* Prilika — zajednička logika kartica i filtara.
   Jedna definicija za popise, kartu i pretragu: JS upravlja STANJEM
   (koji su predmeti vidljivi), CSS upravlja IZGLEDOM. */
(function () {
  "use strict";

  function esc(s) {
    var d = document.createElement("div");
    d.textContent = s || "";
    return d.innerHTML;
  }

  function danPlural(n) {
    return n % 10 === 1 && n % 100 !== 11 ? "dan" : "dana";
  }

  function card(it) {
    var loc = it.g ? esc(it.g) + (it.z ? ", " + esc(it.z) : "") :
              (it.z ? esc(it.z) : "Lokacija nije utvrđena");
    var price = it.p ? "<strong>" + esc(it.p) + "</strong>" :
                '<span class="muted">Cijena nije objavljena</span>';
    var chip = it.d ? ' <span class="chip">−' + esc(it.d) + "</span>" : "";
    var ic = document.querySelector('#ikone [data-ty="' + it.ty + '"]') ||
             document.querySelector('#ikone [data-ty="ostalo"]');
    var meta = [];
    if (it.a) meta.push(esc(it.a));
    if (it.pm) meta.push(esc(it.pm));
    var rok = it.dl !== null && it.dl !== undefined
      ? '<span class="chip chip-rok">još ' + it.dl + " " + danPlural(it.dl) + "</span>"
      : (it.e ? "završava " + esc(it.e) : esc(it.s));
    return '<li class="card"><article>' +
      '<div class="card-media mb-' + esc(it.ty) + '">' + (ic ? ic.innerHTML : "") +
      '<span class="mtype">' + esc(it.t) + "</span>" +
      '<span class="status">' + esc(it.s) + "</span></div>" +
      '<div class="card-body">' +
      '<p class="card-price">' + price + chip + "</p>" +
      '<h3><a href="' + esc(it.u) + '">' + esc(it.n) + "</a></h3>" +
      '<p class="card-loc">' + loc + "</p>" +
      (meta.length ? '<p class="card-meta">' + meta.join(" · ") + "</p>" : "") +
      '<p class="card-status">' + rok + "</p>" +
      "</div></article></li>";
  }

  /* Pročitaj formu -> funkcija koja kaže prolazi li predmet filtre. */
  function predicate(form) {
    var scope = form.dataset;
    var f = new FormData(form);
    var types = f.getAll("ty");
    var sk = f.get("sk"), pk = f.get("pk");
    var pmin = parseFloat(f.get("pmin")), pmax = parseFloat(f.get("pmax"));
    var amin = parseFloat(f.get("amin"));
    return function (it) {
      if (scope.county && it.zs !== scope.county) return false;
      if (scope.city && it.gs !== scope.city) return false;
      if (scope.type && it.ty !== scope.type) return false;
      if (types.length && types.indexOf(it.ty) === -1) return false;
      if (sk && it.sk !== sk) return false;
      if (pk && it.pk !== pk) return false;
      if (!isNaN(pmin) && (it.pn === null || it.pn < pmin)) return false;
      if (!isNaN(pmax) && (it.pn === null || it.pn > pmax)) return false;
      if (!isNaN(amin) && (it.an === null || it.an < amin)) return false;
      return true;
    };
  }

  function sortHits(hits, sort) {
    var key = { dn: "dn", pn_asc: "pn", pn_desc: "pn",
                mn: "mn", an: "an", ei: "ei" }[sort] || "dn";
    var asc = (sort === "pn_asc" || sort === "mn" || sort === "ei");
    hits.sort(function (x, y) {
      var a = x[key], b = y[key];
      if (a === null || a === undefined || a === "") return 1;
      if (b === null || b === undefined || b === "") return -1;
      if (a < b) return asc ? -1 : 1;
      if (a > b) return asc ? 1 : -1;
      return 0;
    });
    return hits;
  }

  /* Broj aktivnih filtara (za oznaku na gumbu "Filteri"). */
  function countActive(form) {
    var f = new FormData(form), n = f.getAll("ty").length;
    ["sk", "pk", "pmin", "pmax", "amin"].forEach(function (k) {
      if (f.get(k)) n += 1;
    });
    return n;
  }

  /* Zajedničko ožičenje trake: sklapanje na mobitelu + brojač + reset. */
  function wireFilterbar(form, onChange) {
    form.hidden = false;                       // bez JS-a traka ne postoji
    var toggle = form.querySelector(".f-toggle");
    var badge = form.querySelector("#f-aktivnih");
    toggle.addEventListener("click", function () {
      var open = form.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    function refreshBadge() {
      var n = countActive(form);
      badge.hidden = n === 0;
      badge.textContent = n;
    }
    form.addEventListener("input", function () { refreshBadge(); onChange(); });
    form.querySelector("#f-reset").addEventListener("click", function () {
      form.reset(); refreshBadge(); onChange();
    });
    refreshBadge();
  }

  window.Prilika = { esc: esc, card: card, predicate: predicate,
                    sortHits: sortHits, countActive: countActive,
                    wireFilterbar: wireFilterbar, danPlural: danPlural };
})();
