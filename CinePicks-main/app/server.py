# -*- coding: utf-8 -*-
"""
CineChat AI - Backend server (Python standard library, tanpa framework).

Stack ringan & efisien:
  - http.server ThreadingHTTPServer (multi-thread, stdlib)
  - engine.py : BM25 search + rule-based reasoning + multi-criteria decision
  - vision.py : OCR (tesseract) + analisis warna (ImageMagick) untuk upload foto

Jalankan:  python3 app/server.py  ->  http://localhost:8000
"""
import json
import os
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(APP_DIR, "static")
sys.path.insert(0, APP_DIR)

from engine import MovieEngine          # noqa: E402
from vision import analyze_photo        # noqa: E402

PORT = int(os.environ.get("PORT", "8000"))
MAX_UPLOAD = 10 * 1024 * 1024           # 10 MB
MAX_MESSAGE = 1000                      # karakter
RATE_LIMIT_WINDOW = 60                  # detik
RATE_LIMIT_MAX = 120                    # request per window per IP
SESSION_TTL = 30 * 60                   # 30 menit

# Rate limit sederhana per IP (sliding window)
_RATE = {}          # ip -> [timestamps]
_SESSIONS = {}      # session_id -> {"query": str, "page": int, "ts": float}

SECURITY_HEADERS = [
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Content-Security-Policy",
     "default-src 'self'; img-src 'self' https://image.tmdb.org data: blob:; "
     "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'"),
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
]

FOLLOWUP_RE = re.compile(r"^(lagi|lainnya|yang lain|lanjut|next|more|another|tambah|masih ada)\b", re.IGNORECASE)

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
    ".webp": "image/webp",
    ".json": "application/json; charset=utf-8",
}

print("Memuat dataset film (sekali di awal)...")
t0 = time.time()
ENGINE = MovieEngine()
print(f"Siap: {len(ENGINE.movies)} film, {len(ENGINE.postings)} kosakata, "
      f"indeks BM25 dibangun dalam {time.time() - t0:.2f}s")


def _purge_sessions():
    """Hapus sesi yang kedaluwarsa (SESSION_TTL) agar memori tidak membengkak."""
    now = time.time()
    for k in [k for k, v in _SESSIONS.items() if now - v.get("ts", 0) > SESSION_TTL]:
        _SESSIONS.pop(k, None)


NO_CONTEXT_REPLY = {
    "reply": "Belum ada pencarian sebelumnya. Coba sebutkan dulu genre, mood, atau judul film, "
             "misalnya: 'film action terbaik'. Setelah itu kamu bisa ketik 'lagi' atau memperhalus, "
             "misalnya 'tanpa horor' atau 'rating di atas 8'.",
    "movies": [], "lang": "id",
}


def refine_session(sess, delta):
    """Terapkan penghalusan (delta) ke sesi, jalankan ulang query dasar dengan konteks baru.

    Konteks baru hanya disimpan jika menghasilkan film; jika kosong, filter sebelumnya dipertahankan.
    """
    new_ctx = ENGINE.merge_ctx(sess.get("ctx"), delta)
    result = ENGINE.chat(sess["query"], page=0, ctx=new_ctx)
    lang = result.get("lang", "id")
    parts = ENGINE.describe_delta(delta, lang)
    if result.get("movies") or delta.get("reset"):
        sess["ctx"], sess["page"], sess["ts"] = new_ctx, 0, time.time()
        head = ("Oke, pencarian diperhalus: " if lang == "id" else "Okay, refined: ") + "; ".join(parts) + ".\n"
        result["reply"] = head + result.get("reply", "")
        return result
    return {
        "reply": ("Tidak ada film yang cocok dengan filter itu (%s). Filter sebelumnya tetap dipakai. "
                  "Coba longgarkan, atau ketik 'reset filter'." % "; ".join(parts)) if lang == "id" else
                 ("No movies match that filter (%s). Previous filters are kept. "
                  "Try loosening it, or type 'reset filter'." % "; ".join(parts)),
        "movies": [], "lang": lang,
    }


# ----------------------------------------------------------------------------
# Utilitas multipart (parser multipart/form-data sederhana)
# ----------------------------------------------------------------------------
def parse_multipart(body, content_type):
    m = re.search(r'boundary=(?:"([^"]+)"|([^;]+))', content_type or "")
    if not m:
        return []
    boundary = (m.group(1) or m.group(2)).strip().encode()
    parts = []
    for raw in body.split(b"--" + boundary):
        raw = raw.strip(b"\r\n")
        if not raw or raw == b"--":
            continue
        header_block, sep, data = raw.partition(b"\r\n\r\n")
        if not sep:
            continue
        headers = {}
        for line in header_block.split(b"\r\n"):
            if b":" in line:
                k, v = line.split(b":", 1)
                headers[k.strip().lower().decode("latin-1")] = v.strip().decode("latin-1")
        cd = headers.get("content-disposition", "")
        name_m = re.search(r'name="([^"]*)"', cd)
        fn_m = re.search(r'filename="([^"]*)"', cd)
        if data.endswith(b"\r\n"):
            data = data[:-2]
        parts.append({
            "name": name_m.group(1) if name_m else None,
            "filename": fn_m.group(1) if fn_m else None,
            "content_type": headers.get("content-type", ""),
            "data": data,
        })
    return parts


def resolve_static(rel_path):
    """Resolve path statis dengan aman dari path traversal. Return None jika di luar STATIC_DIR."""
    safe = os.path.normpath(rel_path).lstrip("/")
    full = os.path.join(STATIC_DIR, safe)
    if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
        return None
    return full


# ----------------------------------------------------------------------------
# HTTP handler
# ----------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "CinePicks/2.0"

    def version_string(self):
        return self.server_version

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    def _sec_headers(self):
        for k, v in SECURITY_HEADERS:
            self.send_header(k, v)

    def _check_rate(self):
        """Rate limit per IP (sliding window). Return True jika boleh lanjut."""
        ip = self.client_address[0]
        now = time.time()
        hits = [t for t in _RATE.get(ip, []) if now - t < RATE_LIMIT_WINDOW]
        if len(hits) >= RATE_LIMIT_MAX:
            _RATE[ip] = hits
            return False
        hits.append(now)
        _RATE[ip] = hits
        return True

    # ---------------------------------------------------------- respons JSON
    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self._sec_headers()
        self.end_headers()
        self.wfile.write(body)

    # ---------------------------------------------------------- file statis
    def _static(self, rel_path):
        full = resolve_static(rel_path)
        if not full:
            self.send_error(404, "Not Found")
            return
        ext = os.path.splitext(full)[1].lower()
        ctype = MIME.get(ext, "application/octet-stream")
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self._sec_headers()
        self.end_headers()
        self.wfile.write(body)

    # ---------------------------------------------------------- GET
    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._static("index.html")
        elif path.startswith("/static/"):
            self._static(path[len("/static/"):])
        elif path == "/api/health":
            self._json({
                "status": "ok",
                "movies": len(ENGINE.movies),
                "vocab": len(ENGINE.postings),
                "uptime_s": round(time.time() - t0, 1),
            })
        elif path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        else:
            self.send_error(404, "Not Found")

    # ---------------------------------------------------------- POST
    def do_POST(self):
        path = urlparse(self.path).path
        if not self._check_rate():
            self._json({"error": "Terlalu banyak request. Coba lagi nanti."}, 429)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length > MAX_UPLOAD + 1024 * 1024:
            self._json({"error": "Payload terlalu besar."}, 413)
            return
        body = self.rfile.read(length) if length else b""

        if path == "/api/chat":
            self._handle_chat(body)
        elif path == "/api/upload":
            self._handle_upload(body)
        else:
            self._json({"error": "Endpoint tidak ditemukan."}, 404)

    # ---------------------------------------------------------- API chat
    def _handle_chat(self, body):
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json({"error": "JSON tidak valid."}, 400)
            return
        message = str(payload.get("message", "") or "").strip()
        if len(message) > MAX_MESSAGE:
            self._json({"error": "Pesan terlalu panjang (maks %d karakter)." % MAX_MESSAGE}, 400)
            return
        if not message:
            self._json({"error": "Pesan kosong."}, 400)
            return

        sid = str(payload.get("session_id", "") or "")[:64]
        _purge_sessions()
        sess = _SESSIONS.get(sid) if sid else None
        has_ctx = bool(sess and sess.get("query"))

        # Multi-turn 1: penghalusan pencarian ("yang tahun 2020 ke atas", "tanpa horor", "rating di atas 8")
        delta = ENGINE.parse_refinement(message)
        if delta:
            if has_ctx:
                self._json(refine_session(sess, delta))
                return
            if any(k in delta for k in ("reset", "min_rating", "year_min", "year_max", "exclude_genres", "prefer")):
                self._json(NO_CONTEXT_REPLY)
                return

        # Multi-turn 2: "lagi", "lainnya", "lanjut", dll -> halaman berikutnya
        if FOLLOWUP_RE.match(message):
            if not has_ctx:
                self._json(NO_CONTEXT_REPLY)
                return
            nxt = sess.get("page", 0) + 1
            result = ENGINE.chat(sess["query"], page=nxt, ctx=sess.get("ctx"))
            if result.get("movies"):
                sess["page"] = nxt
                sess["ts"] = time.time()
            else:
                result = {
                    "reply": "Sudah tidak ada rekomendasi lain untuk pencarian itu. "
                             "Coba ubah genre, mood, atau tahunnya.",
                    "movies": [], "lang": result.get("lang", "id"),
                }
            self._json(result)
            return

        # Pencarian baru: simpan sebagai konteks (hanya jika ada hasil, agar sapaan tidak menimpa konteks)
        result = ENGINE.chat(message, page=0)
        if sid and result.get("movies"):
            _SESSIONS[sid] = {"query": message, "page": 0, "ctx": {}, "ts": time.time()}
        self._json(result)

    # ---------------------------------------------------------- API upload
    def _handle_upload(self, body):
        ctype = self.headers.get("Content-Type", "")
        parts = parse_multipart(body, ctype)
        file_part = None
        for p in parts:
            if p.get("filename"):
                file_part = p
                break
        if not file_part:
            self._json({"error": "Tidak ada file foto pada request. Gunakan field 'file'."}, 400)
            return
        if not (file_part.get("content_type", "").startswith("image/") or file_part["data"]):
            self._json({"error": "File harus berupa gambar."}, 400)
            return
        if len(file_part["data"]) > MAX_UPLOAD:
            self._json({"error": "Ukuran gambar maksimal 10 MB."}, 413)
            return
        try:
            result = analyze_photo(file_part["data"], ENGINE)
        except Exception as exc:  # jangan buat server mati
            self._json({"error": "Gagal menganalisis foto: %s" % exc}, 500)
            return
        if "error" in result:
            self._json(result, 400)
            return
        self._json(result)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("=" * 56)
    print("  CineChat AI berjalan di: http://localhost:%d" % PORT)
    print("  Tekan Ctrl+C untuk berhenti.")
    print("=" * 56)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer dihentikan.")
        server.shutdown()


if __name__ == "__main__":
    main()
