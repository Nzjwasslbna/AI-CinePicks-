/* CinePicks - Frontend (vanilla JS, tanpa framework) */
(function () {
  "use strict";

  // Helper pencarian elemen yang aman: jika elemen tidak ada (mis. HTML lama
  // ter-cache), kembalikan stub agar aplikasi tetap berjalan dan tidak mati total.
  function $(id) {
    var el = document.getElementById(id);
    if (el) return el;
    return {
      addEventListener: function () {}, querySelector: function () { return { hidden: false }; },
      style: {}, classList: { add: function () {}, remove: function () {} },
      value: "", placeholder: "", textContent: "", hidden: false, disabled: false,
      scrollTop: 0, scrollHeight: 0, files: [],
      remove: function () {}, appendChild: function () {}, insertAdjacentHTML: function () {},
      removeAttribute: function () {}, setAttribute: function () {}, focus: function () {},
      click: function () {},
    };
  }

  var chatEl = $("chat");
  var formEl = $("composer");
  var inputEl = $("textInput");
  var sendBtn = $("sendBtn");
  var sendIco = sendBtn.querySelector(".send-ico");
  var spinEl = sendBtn.querySelector(".spin");
  var uploadBtn = $("uploadBtn");
  var fileInput = $("fileInput");
  var previewEl = $("preview");
  var previewImg = $("previewImg");
  var previewName = $("previewName");
  var previewClear = $("previewClear");
  var chipsEl = $("chips");
  var heroEl = $("hero");
  var heroActions = $("heroActions");
  var statusEl = $("statusText");
  var listBtn = $("listBtn");
  var listCount = $("listCount");
  var drawerEl = $("drawer");
  var drawerBackdrop = $("drawerBackdrop");
  var drawerClose = $("drawerClose");
  var drawerBody = $("drawerBody");
  var drawerClear = $("drawerClear");
  var tabWatch = $("tabWatch");
  var tabFav = $("tabFav");
  var cntWatch = $("cntWatch");
  var cntFav = $("cntFav");

  var pendingFile = null;
  var previewUrl = null;
  var busy = false;
  var firstSend = true;

  // ID sesi untuk dukungan multi-turn ("lagi", "lainnya") di backend
  var sessionId = null;
  try {
    sessionId = localStorage.getItem("cinepicks_sid");
    if (!sessionId) {
      sessionId = "s" + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
      localStorage.setItem("cinepicks_sid", sessionId);
    }
  } catch (e) {
    // localStorage diblokir (private mode) — fallback ke sesi per halaman
    sessionId = "s" + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
  }

  /* ---------------- util ---------------- */
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function nl2br(s) { return esc(s).replace(/\n/g, "<br>"); }
  function nowTime() {
    return new Date().toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
  }
  function scrollDown() { chatEl.scrollTop = chatEl.scrollHeight; }

  /* ---------------- watchlist & favorit (disimpan di browser) ---------------- */
  var LIST_KEY = "cinepicks_lists_v1";
  var LIST_MAX = 200;
  var lists = { watch: [], fav: [] };
  var movieIndex = {};          // id -> data film dari hasil chat (untuk tombol di kartu)
  var drawerTab = "watch";

  function loadLists() {
    try {
      var raw = localStorage.getItem(LIST_KEY);
      if (!raw) return;
      var o = JSON.parse(raw) || {};
      ["watch", "fav"].forEach(function (k) {
        var arr = Array.isArray(o[k]) ? o[k] : [];
        lists[k] = arr.filter(function (m) { return m && m.id != null && m.title; }).slice(0, LIST_MAX);
      });
    } catch (e) { /* storage diblokir / rusak: mulai dari kosong */ }
  }
  function saveLists() {
    try { localStorage.setItem(LIST_KEY, JSON.stringify(lists)); } catch (e) {}
  }
  function slim(m) {
    return {
      id: m.id, title: m.title, year: m.year, rating: m.rating,
      genres: (m.genres || []).slice(0, 3), poster: m.poster || "",
    };
  }
  function listPos(name, id) {
    var arr = lists[name];
    for (var i = 0; i < arr.length; i++) if (String(arr[i].id) === String(id)) return i;
    return -1;
  }
  function inList(name, id) { return listPos(name, id) >= 0; }
  function toggleList(name, m) {
    var pos = listPos(name, m.id);
    if (pos >= 0) lists[name].splice(pos, 1);
    else lists[name].unshift(slim(m));
    if (lists[name].length > LIST_MAX) lists[name].length = LIST_MAX;
    saveLists();
    refreshLists();
  }
  function actLabel(kind, on) {
    if (kind === "watch") return on ? "&#10003; Di Watchlist" : "&#43; Watchlist";
    return on ? "&#9829; Favorit" : "&#9825; Favorit";
  }
  function actBtn(kind, m) {
    var on = inList(kind, m.id);
    return '<button type="button" class="act' + (on ? " on" : "") + '" data-act="' + kind +
      '" data-id="' + esc(m.id) + '" aria-pressed="' + (on ? "true" : "false") + '">' +
      actLabel(kind, on) + "</button>";
  }
  function refreshLists() {
    var btns = document.querySelectorAll(".act");
    for (var i = 0; i < btns.length; i++) {
      var b = btns[i];
      var on = inList(b.getAttribute("data-act"), b.getAttribute("data-id"));
      b.className = "act" + (on ? " on" : "");
      b.setAttribute("aria-pressed", on ? "true" : "false");
      b.innerHTML = actLabel(b.getAttribute("data-act"), on);
    }
    listCount.textContent = String(lists.watch.length + lists.fav.length);
    cntWatch.textContent = String(lists.watch.length);
    cntFav.textContent = String(lists.fav.length);
    if (!drawerEl.hidden) renderDrawer();
  }
  loadLists();

  // Fallback gambar gagal dimuat (CSP-safe, tanpa inline onerror)
  chatEl.addEventListener("error", function (e) {
    if (e.target && e.target.tagName === "IMG") e.target.remove();
  }, true);

  function fetchTimeout(url, opts, ms) {
    var timer = null;
    var req = fetch(url, opts);
    if (typeof AbortController !== "undefined") {
      var ctrl = new AbortController();
      timer = setTimeout(function () { ctrl.abort(); }, ms || 20000);
      req = fetch(url, Object.assign({}, opts, { signal: ctrl.signal }));
    }
    // Bersihkan timer tanpa .finally() agar kompatibel dengan browser lama
    req.then(function () { if (timer) clearTimeout(timer); },
             function () { if (timer) clearTimeout(timer); });
    return req;
  }

  /* ---------------- render ---------------- */
  function msgShell(role, name) {
    return (
      '<div class="msg ' + role + '">' +
        '<div class="msg-head">' +
          '<span class="avatar">' + (role === "bot" ? "C" : "K") + "</span>" +
          '<span class="msg-name">' + esc(name) + '</span>' +
          '<span class="msg-time">' + nowTime() + "</span>" +
        "</div>" +
      "</div>"
    );
  }

  function addUser(text, imageUrl) {
    var div = document.createElement("div");
    div.innerHTML = msgShell("user", "Kamu");
    var inner = "";
    if (imageUrl) {
      inner += '<img src="' + imageUrl + '" alt="foto terkirim" style="max-width:230px;border-radius:12px;display:block;margin-bottom:6px;">';
    }
    if (text) inner += '<div class="bubble">' + nl2br(text) + "</div>";
    div.firstChild.insertAdjacentHTML("beforeend", inner);
    chatEl.appendChild(div.firstChild);
    scrollDown();
  }

  function addTyping() {
    var div = document.createElement("div");
    div.innerHTML = msgShell("bot", "CinePicks");
    var msgEl = div.firstChild;
    if (!msgEl) {
      msgEl = document.createElement("div");
      msgEl.className = "msg bot";
    }
    msgEl.insertAdjacentHTML(
      "beforeend",
      '<div class="bubble typing"><span></span><span></span><span></span></div>'
    );
    chatEl.appendChild(msgEl);
    scrollDown();
    return msgEl;
  }

  function movieCard(m) {
    var letter = esc((m.title || "?").charAt(0));
    var img = m.poster
      ? '<img src="' + esc(m.poster) + '" alt="' + esc(m.title) + '" loading="lazy">'
      : "";
    var poster =
      '<div class="poster"><span class="poster-letter">' + letter + "</span>" + img +
      '<span class="badge">&#9733; ' + esc(m.rating) + "</span>" +
      '<span class="badge-year">' + esc(m.year) + "</span></div>";
    var genres = (m.genres || []).map(function (g) { return "<span>" + esc(g) + "</span>"; }).join("");
    var stars = "";
    var r = Math.round((m.rating || 0) / 2);
    for (var i = 0; i < 5; i++) stars += i < r ? "&#9733;" : "&#9734;";
    return (
      '<div class="card">' +
        poster +
        '<div class="info">' +
          '<div class="title">' + esc(m.title) + "</div>" +
          '<div class="meta"><span class="star">' + stars + "</span> " + esc(m.rating) +
          " &middot; " + esc((m.votes || 0).toLocaleString("id")) + " votes</div>" +
          '<div class="genres">' + genres + "</div>" +
          (m.reason ? '<div class="why"><b>Kenapa direkomendasikan:</b> ' + nl2br(m.reason) + "</div>" : "") +
          (m.description || m.overview
            ? '<div class="syn"><b>Deskripsi:</b> ' + esc(m.description || m.overview) + "</div>"
            : "") +
          '<div class="actions">' + actBtn("watch", m) + actBtn("fav", m) + "</div>" +
        "</div>" +
      "</div>"
    );
  }

  // Chip cepat untuk multi-turn: "lagi" + cara memperhalus pencarian
  var QUICK = [
    ["Lagi", "lagi"],
    ["Lebih baru", "lebih baru"],
    ["Rating 8+", "rating di atas 8"],
    ["Tanpa horor", "tanpa horor"],
    ["Reset filter", "reset filter"],
  ];
  function quickRow() {
    return '<div class="quick" aria-label="Perhalus pencarian"><span class="quick-label">Perhalus:</span>' +
      QUICK.map(function (q) {
        return '<button type="button" class="chip quick-chip" data-q="' + esc(q[1]) + '">' + esc(q[0]) + "</button>";
      }).join("") + "</div>";
  }

  function addBot(data, fromChat) {
    var div = document.createElement("div");
    div.innerHTML = msgShell("bot", "CinePicks");
    var inner = '<div class="bubble">' + nl2br(data.reply || "") + "</div>";
    if (data.movies && data.movies.length) {
      data.movies.forEach(function (m) { movieIndex[m.id] = m; });
      inner += '<div class="bubble" style="max-width:100%;background:transparent;border:none;padding:0;">' +
        '<div class="movies">' + data.movies.map(movieCard).join("") + "</div></div>";
      if (fromChat) {
        // hanya hasil terbaru yang punya chip (chip lama merujuk konteks yang sudah berganti)
        var olds = chatEl.querySelectorAll ? chatEl.querySelectorAll(".quick") : [];
        for (var i = 0; i < olds.length; i++) olds[i].remove();
        inner += quickRow();
      }
    }
    div.firstChild.insertAdjacentHTML("beforeend", inner);
    chatEl.appendChild(div.firstChild);
    scrollDown();
  }

  function addError(text) {
    var div = document.createElement("div");
    div.innerHTML = msgShell("bot", "CinePicks");
    div.firstChild.insertAdjacentHTML("beforeend", '<div class="bubble err">' + nl2br(text) + "</div>");
    chatEl.appendChild(div.firstChild);
    scrollDown();
  }

  function setBusy(v) {
    busy = v;
    sendBtn.disabled = v;
    uploadBtn.disabled = v;
    sendIco.hidden = v;
    spinEl.hidden = !v;
  }

  /* ---------------- API ---------------- */
  function postChat(message) {
    return fetchTimeout("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: message, session_id: sessionId }),
    }, 20000).then(function (r) { return r.json(); });
  }
  function postUpload(file, caption) {
    var fd = new FormData();
    fd.append("file", file);
    if (caption) fd.append("caption", caption);
    return fetchTimeout("/api/upload", { method: "POST", body: fd }, 60000).then(function (r) { return r.json(); });
  }

  /* ---------------- aksi kirim ---------------- */
  function submit() {
    var text = inputEl.value.trim();
    var hasImage = !!pendingFile;
    if (busy || (!text && !hasImage)) return;

    var file = pendingFile;
    var imgUrl = null;
    if (file) imgUrl = URL.createObjectURL(file);

    if (firstSend) {
      firstSend = false;
      heroEl.classList.add("hidden");
    }
    addUser(text || "Analisis foto ini:", imgUrl);
    inputEl.value = "";
    clearPreview();
    var typing = addTyping();
    setBusy(true);

    var p = hasImage ? postUpload(file, text) : postChat(text);

    function finish() {
      setBusy(false);
      inputEl.focus();
    }
    p.then(function (data) {
      typing.remove();
      if (data && data.error) addError("Maaf: " + data.error);
      else addBot(data, !hasImage);
      finish();
    }, function () {
      typing.remove();
      addError("Gagal terhubung ke server. Pastikan backend berjalan.");
      finish();
    });
  }

  /* ---------------- upload ---------------- */
  function clearPreview() {
    if (previewUrl) { URL.revokeObjectURL(previewUrl); previewUrl = null; }
    pendingFile = null;
    fileInput.value = "";
    previewImg.removeAttribute("src");
    previewName.textContent = "";
    previewEl.hidden = true;
  }

  uploadBtn.addEventListener("click", function () { fileInput.click(); });
  fileInput.addEventListener("change", function () {
    var f = fileInput.files && fileInput.files[0];
    if (!f) return;
    if (!f.type || f.type.indexOf("image/") !== 0) {
      addError("File harus berupa gambar (JPEG, PNG, WebP, GIF, BMP).");
      fileInput.value = "";
      return;
    }
    if (f.size > 10 * 1024 * 1024) {
      addError("Ukuran gambar maksimal 10 MB.");
      fileInput.value = "";
      return;
    }
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = URL.createObjectURL(f);
    pendingFile = f;
    previewImg.src = previewUrl;
    previewName.textContent = f.name + " (" + Math.round(f.size / 1024) + " KB)";
    previewEl.hidden = false;
    inputEl.placeholder = "Tambahkan catatan (opsional) lalu kirim...";
  });
  previewClear.addEventListener("click", function () {
    clearPreview();
    inputEl.placeholder = "Genre, mood, judul, atau tahun...";
  });

  /* ---------------- chips ---------------- */
  function chipClick(e) {
    var btn = e.target.closest(".chip");
    if (!btn || busy) return;
    inputEl.value = btn.getAttribute("data-q");
    submit();
  }
  chipsEl.addEventListener("click", chipClick);
  heroActions.addEventListener("click", chipClick);

  /* ---------------- tombol kartu + chip penghalusan ---------------- */
  chatEl.addEventListener("click", function (e) {
    var act = e.target.closest ? e.target.closest(".act") : null;
    if (act) {
      var m = movieIndex[act.getAttribute("data-id")];
      if (m) toggleList(act.getAttribute("data-act"), m);
      return;
    }
    var q = e.target.closest ? e.target.closest(".quick-chip") : null;
    if (q && !busy) {
      inputEl.value = q.getAttribute("data-q");
      submit();
    }
  });

  /* ---------------- panel Watchlist / Favorit ---------------- */
  function safePoster(u) {
    return typeof u === "string" && u.indexOf("https://image.tmdb.org/") === 0 ? u : "";
  }
  function renderDrawer() {
    var arr = lists[drawerTab];
    tabWatch.className = "tab" + (drawerTab === "watch" ? " on" : "");
    tabFav.className = "tab" + (drawerTab === "fav" ? " on" : "");
    if (!arr.length) {
      drawerBody.innerHTML = '<div class="empty">' + (drawerTab === "watch"
        ? "Watchlist masih kosong. Tekan <b>+ Watchlist</b> pada kartu film untuk menyimpan film yang ingin kamu tonton nanti."
        : "Belum ada favorit. Tekan <b>&#9825; Favorit</b> pada film yang kamu suka.") + "</div>";
      return;
    }
    var other = drawerTab === "watch" ? "fav" : "watch";
    drawerBody.innerHTML = arr.map(function (m) {
      var img = safePoster(m.poster) ? '<img src="' + esc(safePoster(m.poster)) + '" alt="" loading="lazy">' : "";
      var genres = (m.genres || []).map(esc).join(" &middot; ");
      return '<div class="li" data-id="' + esc(m.id) + '">' +
        '<div class="li-poster"><span>' + esc((m.title || "?").charAt(0)) + "</span>" + img + "</div>" +
        '<div class="li-info">' +
          '<div class="li-title">' + esc(m.title) + "</div>" +
          '<div class="li-meta">' + esc(m.year || "") + " &middot; &#9733; " + esc(m.rating) + "</div>" +
          '<div class="li-meta">' + genres + "</div>" +
          '<div class="li-actions">' +
            '<button type="button" class="mini" data-dact="similar">Mirip</button>' +
            '<button type="button" class="mini" data-dact="move">' +
              (other === "fav" ? "&#9829; Ke Favorit" : "&#43; Ke Watchlist") + "</button>" +
            '<button type="button" class="mini danger" data-dact="remove">Hapus</button>' +
          "</div>" +
        "</div></div>";
    }).join("");
  }
  function openDrawer(tab) {
    if (tab) drawerTab = tab;
    drawerEl.hidden = false;
    renderDrawer();
  }
  function closeDrawer() { drawerEl.hidden = true; }

  // Poster gagal dimuat (offline / diblokir): hapus <img> agar huruf pengganti tampil
  drawerBody.addEventListener("error", function (e) {
    if (e.target && e.target.tagName === "IMG") e.target.remove();
  }, true);

  listBtn.addEventListener("click", function () { openDrawer(); });
  drawerClose.addEventListener("click", closeDrawer);
  drawerBackdrop.addEventListener("click", closeDrawer);
  tabWatch.addEventListener("click", function () { drawerTab = "watch"; renderDrawer(); });
  tabFav.addEventListener("click", function () { drawerTab = "fav"; renderDrawer(); });
  drawerClear.addEventListener("click", function () {
    if (!lists[drawerTab].length) return;
    if (!window.confirm("Kosongkan " + (drawerTab === "watch" ? "Watchlist" : "Favorit") + "?")) return;
    lists[drawerTab] = [];
    saveLists();
    refreshLists();
  });
  drawerBody.addEventListener("click", function (e) {
    var btn = e.target.closest ? e.target.closest("[data-dact]") : null;
    if (!btn) return;
    var li = btn.closest(".li");
    var id = li && li.getAttribute("data-id");
    var pos = listPos(drawerTab, id);
    if (pos < 0) return;
    var m = lists[drawerTab][pos];
    var what = btn.getAttribute("data-dact");
    if (what === "remove") {
      lists[drawerTab].splice(pos, 1);
    } else if (what === "move") {
      var other = drawerTab === "watch" ? "fav" : "watch";
      lists[drawerTab].splice(pos, 1);
      if (!inList(other, m.id)) lists[other].unshift(m);
    } else if (what === "similar") {
      if (busy) return;
      closeDrawer();
      inputEl.value = "mirip " + m.title;
      submit();
      return;
    }
    saveLists();
    refreshLists();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !drawerEl.hidden) closeDrawer();
  });
  refreshLists();

  /* ---------------- form ---------------- */
  formEl.addEventListener("submit", function (e) {
    e.preventDefault();
    submit();
  });

  /* ---------------- health ---------------- */
  // Tampilkan error tak terduga di chat agar tidak gagal senyap
  window.addEventListener("error", function (e) {
    if (e && e.message && chatEl && chatEl.appendChild) {
      addError("Error: " + e.message);
    }
  });

  fetch("/api/health")
    .then(function (r) { return r.json(); })
    .then(function (h) {
      if (h && h.status === "ok") statusEl.textContent = "online · " + h.movies + " film";
      else statusEl.textContent = "offline";
    })
    .catch(function () {
      statusEl.textContent = "offline";
      document.querySelector(".dot").style.background = "#e74c3c";
      document.querySelector(".dot").style.boxShadow = "none";
    });
})();
