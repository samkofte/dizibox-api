import time
import json
import urllib.request
import urllib.parse
from dataclasses import asdict
from flask import Flask, jsonify, request, Response, render_template_string

from dizibox_api.client import DiziboxClient
from dizibox_api.exceptions import DiziboxAPIError, NotFoundError, CloudflareBlockedError

app = Flask(__name__)
client = DiziboxClient()

CHUNK_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://dbx.molystream.org/",
    "Accept": "*/*",
}


@app.before_request
def start_timer():
    request._start_time = time.time()


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    if hasattr(request, "_start_time"):
        elapsed_ms = round((time.time() - request._start_time) * 1000, 2)
        response.headers["X-Response-Time-Ms"] = str(elapsed_ms)
    return response


@app.route("/favicon.ico")
def favicon():
    return Response(status=204)


# -------------------------------------------------------------
# REST API Endpoints
# -------------------------------------------------------------

@app.route("/api/cache/stats", methods=["GET"])
def api_cache_stats():
    """Cache performance stats."""
    return jsonify({"status": "success", "data": client.cache_stats()})


_poster_cache = {}

def get_reliable_poster(title: str, fallback_url: str = None) -> str:
    """Fetch high-res poster from TVMaze API for 100% reliable image loading."""
    clean_title = title.split("izle")[0].split("(")[0].strip()
    if clean_title in _poster_cache:
        return _poster_cache[clean_title]

    try:
        url = f"https://api.tvmaze.com/singlesearch/shows?q={urllib.parse.quote(clean_title)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            img_url = data.get("image", {}).get("medium") or data.get("image", {}).get("original")
            if img_url:
                _poster_cache[clean_title] = img_url
                return img_url
    except Exception:
        pass

    _poster_cache[clean_title] = fallback_url or f"https://via.placeholder.com/200x290?text={urllib.parse.quote(title)}"
    return _poster_cache[clean_title]


@app.route("/api/recent", methods=["GET"])
def api_recent():
    """Get latest episodes."""
    try:
        page = int(request.args.get("page", 1))
        episodes = client.get_recent_episodes(page=page)
        data = []
        for ep in episodes:
            item = asdict(ep)
            item["thumbnail_url"] = get_reliable_poster(ep.series_title, ep.thumbnail_url)
            data.append(item)
        return jsonify({
            "status": "success",
            "page": page,
            "count": len(data),
            "data": data,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/archive", methods=["GET"])
def api_archive():
    """Get master archive series list."""
    try:
        page = int(request.args.get("page", 1))
        series = client.get_archive_series(page=page)
        return jsonify({
            "status": "success",
            "page": page,
            "count": len(series),
            "data": [asdict(s) for s in series],
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/search", methods=["GET"])
def api_search():
    """Search series by title query."""
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"status": "error", "message": "Query parameter 'q' is required"}), 400
    try:
        results = client.search(q)
        data = []
        for s in results:
            item = asdict(s)
            item["poster_url"] = get_reliable_poster(s.title, s.poster_url)
            data.append(item)
        return jsonify({
            "status": "success",
            "query": q,
            "count": len(data),
            "data": data,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/series/<slug>", methods=["GET"])
def api_series_detail(slug):
    """Get series detail, poster, metadata and season episodes."""
    try:
        series = client.get_series(slug)
        res = asdict(series)
        res["poster_url"] = get_reliable_poster(series.title, series.poster_url)
        # Convert season keys to string for JSON serialization
        res["seasons"] = {str(k): v for k, v in res["seasons"].items()}
        return jsonify({"status": "success", "data": res})
    except NotFoundError as e:
        return jsonify({"status": "error", "message": str(e)}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/stream/<episode_slug>", methods=["GET"])
def api_stream(episode_slug):
    """Decrypt MolySTREAM and extract HLS m3u8 playlist."""
    try:
        stream = client.get_episode_stream(episode_slug)
        res = asdict(stream)
        # Point to proxied m3u8 for seamless browser playback
        res["proxied_m3u8_url"] = f"/api/m3u8/{episode_slug}"
        return jsonify({"status": "success", "data": res})
    except NotFoundError as e:
        return jsonify({"status": "error", "message": str(e)}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/m3u8/<episode_slug>", methods=["GET"])
def api_m3u8_proxy(episode_slug):
    """Proxy and rewrite MolySTREAM m3u8 playlist to bypass Referer check and VOD live flag."""
    try:
        stream = client.get_episode_stream(episode_slug)
        r_master = client._session.get(stream.stream_url, headers={"Referer": stream.embed_url})
        if r_master.status_code != 200:
            return Response("Failed to fetch stream", status=502)

        master_text = r_master.text.strip()
        # Find child playlist (e.g. /q/1)
        child_urls = [line.strip() for line in master_text.splitlines() if line.strip().startswith("http")]
        if not child_urls:
            # Maybe single level
            content = master_text
        else:
            child_url = child_urls[0]
            r_child = client._session.get(child_url, headers={"Referer": stream.embed_url})
            content = r_child.text

        # Rewrite video chunk lines to route through /api/chunk
        rewritten_lines = []
        for line in content.splitlines():
            line_s = line.strip()
            if line_s.startswith("http"):
                rewritten_lines.append(f"/api/chunk?url={line_s}")
            else:
                rewritten_lines.append(line_s)

        # Ensure #EXT-X-PLAYLIST-TYPE:VOD and #EXT-X-ENDLIST are present so players don't treat it as LIVE
        m3u8_body = "\n".join(rewritten_lines)
        if "#EXT-X-PLAYLIST-TYPE" not in m3u8_body:
            m3u8_body = m3u8_body.replace("#EXTM3U", "#EXTM3U\n#EXT-X-PLAYLIST-TYPE:VOD")
        if "#EXT-X-ENDLIST" not in m3u8_body:
            m3u8_body += "\n#EXT-X-ENDLIST\n"

        return Response(m3u8_body, mimetype="application/vnd.apple.mpegurl")
    except Exception as e:
        return Response(f"Error generating playlist: {e}", status=500)


@app.route("/api/chunk", methods=["GET"])
def api_chunk_proxy():
    """Proxy video segment chunks with MolySTREAM Referer."""
    chunk_url = request.args.get("url")
    if not chunk_url:
        return Response("Missing url param", status=400)
    try:
        req = urllib.request.Request(chunk_url, headers=CHUNK_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
            return Response(
                data,
                status=resp.status,
                mimetype="video/MP2T",
                headers={
                    "Cache-Control": "public, max-age=86400",
                    "Access-Control-Allow-Origin": "*",
                }
            )
    except Exception as e:
        return Response(f"Error fetching chunk: {e}", status=500)


@app.route("/api/embed/<episode_slug>", methods=["GET"])
def api_embed_page(episode_slug):
    """Direct embed player page with Video.js and proxied VOD stream."""
    try:
        stream = client.get_episode_stream(episode_slug)
        m3u8_url = f"/api/m3u8/{episode_slug}"
        player_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{stream.episode_title}</title>
    <link href="https://vjs.zencdn.net/8.10.0/video-js.css" rel="stylesheet" />
    <style>
        body, html {{ margin: 0; padding: 0; width: 100%; height: 100%; background: #000; overflow: hidden; }}
        .video-js {{ width: 100% !important; height: 100% !important; }}
    </style>
</head>
<body>
    <video id="player" class="video-js vjs-default-skin vjs-big-play-centered" controls autoplay playsinline preload="auto">
        <source src="{m3u8_url}" type="application/x-mpegURL">
    </video>
    <script src="https://vjs.zencdn.net/8.10.0/video.min.js"></script>
    <script>
        const player = videojs('player', {{
            fluid: false,
            liveui: false
        }});
    </script>
</body>
</html>"""
        return render_template_string(player_html)
    except Exception as e:
        return Response(f"Embed error: {e}", status=500)



# -------------------------------------------------------------
# Web Dashboard & Cinema Player UI
# -------------------------------------------------------------

INDEX_HTML = """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dizibox API & Web Kontrol Paneli</title>
    <link href="https://vjs.zencdn.net/8.10.0/video-js.css" rel="stylesheet" />
    <style>
        :root {
            --bg-main: #0b0e14;
            --bg-card: #151922;
            --accent: #e50914;
            --accent-hover: #b20710;
            --text-main: #f0f3f6;
            --text-muted: #8b949e;
            --border: #21262d;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: var(--bg-main);
            color: var(--text-main);
            min-height: 100vh;
        }
        header {
            background: #11141c;
            border-bottom: 1px solid var(--border);
            padding: 14px 24px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            position: sticky;
            top: 0;
            z-index: 100;
        }
        .logo {
            font-size: 22px;
            font-weight: 800;
            color: #fff;
            letter-spacing: -0.5px;
        }
        .logo span { color: var(--accent); }
        .badge {
            background: rgba(229, 9, 20, 0.2);
            color: var(--accent);
            font-size: 11px;
            padding: 2px 6px;
            border-radius: 4px;
            margin-left: 6px;
            border: 1px solid rgba(229, 9, 20, 0.4);
        }
        .search-bar {
            display: flex;
            gap: 8px;
            width: 100%;
            max-width: 440px;
        }
        .search-bar input {
            flex: 1;
            background: #1a1f2c;
            border: 1px solid var(--border);
            color: #fff;
            padding: 8px 14px;
            border-radius: 6px;
            font-size: 13px;
            outline: none;
        }
        .search-bar input:focus { border-color: var(--accent); }
        .search-bar button {
            background: var(--accent);
            color: #fff;
            border: none;
            padding: 8px 16px;
            border-radius: 6px;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s;
        }
        .search-bar button:hover { background: var(--accent-hover); }

        .nav-tabs {
            display: flex;
            gap: 8px;
            padding: 12px 24px;
            background: #11141c;
            border-bottom: 1px solid var(--border);
            overflow-x: auto;
        }
        .tab-btn {
            background: transparent;
            color: var(--text-muted);
            border: 1px solid transparent;
            padding: 6px 14px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            white-space: nowrap;
        }
        .tab-btn:hover { color: #fff; background: #1a1f2c; }
        .tab-btn.active {
            color: #fff;
            background: var(--accent);
            border-color: var(--accent);
        }

        main {
            padding: 24px;
            max-width: 1400px;
            margin: 0 auto;
        }
        .section-title {
            font-size: 18px;
            font-weight: 700;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
            gap: 16px;
        }
        .card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 8px;
            overflow: hidden;
            cursor: pointer;
            transition: transform 0.2s, border-color 0.2s;
            display: flex;
            flex-direction: column;
        }
        .card:hover {
            transform: translateY(-4px);
            border-color: var(--accent);
        }
        .card-poster {
            width: 100%;
            aspect-ratio: 2 / 3;
            background: #1a1f2c;
            position: relative;
            overflow: hidden;
        }
        .card-poster img {
            width: 100%;
            height: 100%;
            object-fit: cover;
        }
        .card-badge {
            position: absolute;
            top: 6px;
            right: 6px;
            background: rgba(0,0,0,0.8);
            color: #ffb703;
            font-size: 11px;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 4px;
        }
        .card-body {
            padding: 10px;
            display: flex;
            flex-direction: column;
            flex: 1;
        }
        .card-title {
            font-size: 13px;
            font-weight: 600;
            color: #fff;
            line-height: 1.3;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
            margin-bottom: 4px;
        }
        .card-sub {
            font-size: 11px;
            color: var(--text-muted);
            margin-top: auto;
        }

        /* Modal */
        .modal-overlay {
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.85);
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 1000;
            padding: 16px;
        }
        .modal {
            background: #151922;
            border: 1px solid var(--border);
            border-radius: 12px;
            width: 100%;
            max-width: 900px;
            max-height: 90vh;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        .modal-header {
            padding: 14px 20px;
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .modal-body {
            padding: 20px;
            overflow-y: auto;
        }
        .close-btn {
            background: transparent;
            border: none;
            color: var(--text-muted);
            font-size: 24px;
            cursor: pointer;
        }
        .close-btn:hover { color: #fff; }

        .episodes-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 10px;
            margin-top: 14px;
        }
        .ep-btn {
            background: #1a1f2c;
            border: 1px solid var(--border);
            color: #fff;
            padding: 10px;
            border-radius: 6px;
            text-align: left;
            font-size: 12px;
            cursor: pointer;
            transition: all 0.2s;
        }
        .ep-btn:hover {
            background: var(--accent);
            border-color: var(--accent);
        }

        .video-wrapper {
            position: relative;
            padding-bottom: 56.25%;
            height: 0;
            background: #000;
            border-radius: 8px;
            overflow: hidden;
            margin-bottom: 16px;
        }
        .video-wrapper .video-js {
            position: absolute;
            top: 0; left: 0; width: 100%; height: 100%;
        }
    </style>
</head>
<body>
    <header>
        <div class="logo">Dizibox<span>API</span> <span class="badge">v1.0</span></div>
        <div class="search-bar">
            <input type="text" id="searchInput" placeholder="Dizi ara (örn: Breaking Bad, Sherlock)..." onkeydown="if(event.key==='Enter') searchSeries()">
            <button onclick="searchSeries()">Ara</button>
        </div>
    </header>

    <div class="nav-tabs">
        <button class="tab-btn active" onclick="loadTab('recent', this)">⚡ Son Eklenen Bölümler</button>
        <button class="tab-btn" onclick="loadTab('archive', this)">📚 Tüm Dizi Kataloğu (4800+)</button>
        <button class="tab-btn" onclick="loadTab('docs', this)">📖 REST API Dokümanı</button>
    </div>

    <main>
        <div class="section-title" id="secTitle">⚡ Son Eklenen Bölümler</div>
        <div class="grid" id="mainGrid"></div>
    </main>

    <!-- Modal -->
    <div class="modal-overlay" id="modalOverlay" onclick="if(event.target===this) closeModal()">
        <div class="modal">
            <div class="modal-header">
                <h3 id="modalTitle">Detay</h3>
                <button class="close-btn" onclick="closeModal()">&times;</button>
            </div>
            <div class="modal-body" id="modalBody"></div>
        </div>
    </div>

    <script src="https://vjs.zencdn.net/8.10.0/video.min.js"></script>
    <script>
        let currentTab = 'recent';
        let playerInstance = null;

        window.onload = () => loadTab('recent');

        function loadTab(tab, btn) {
            currentTab = tab;
            if (btn) {
                document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
            }
            const grid = document.getElementById('mainGrid');
            const title = document.getElementById('secTitle');

            if (tab === 'recent') {
                title.innerText = '⚡ Son Eklenen Bölümler';
                grid.innerHTML = '<p style="color:#8b949e">Yükleniyor...</p>';
                fetch('/api/recent')
                    .then(r => r.json())
                    .then(data => {
                        grid.innerHTML = '';
                        data.data.forEach(ep => {
                            const card = document.createElement('div');
                            card.className = 'card';
                            card.onclick = () => playEpisode(ep.episode_slug, ep.title);
                            const posterSrc = ep.thumbnail_url || 'https://www.dizibox.live/altyazi.png';
                            card.innerHTML = `
                                <div class="card-poster">
                                    <img src="${posterSrc}" alt="" onerror="this.src='https://via.placeholder.com/200x290?text=${encodeURIComponent(ep.series_title || 'Dizibox')}';">
                                    <div class="card-badge">${ep.badge || 'Altyazılı'}</div>
                                </div>
                                <div class="card-body">
                                    <div class="card-title">${ep.title}</div>
                                    <div class="card-sub">${ep.series_title || ''}</div>
                                </div>
                            `;
                            grid.appendChild(card);
                        });
                    });
            } else if (tab === 'archive') {
                title.innerText = '📚 Dizi Kataloğu (Arşiv)';
                grid.innerHTML = '<p style="color:#8b949e">Yükleniyor...</p>';
                fetch('/api/archive')
                    .then(r => r.json())
                    .then(data => {
                        grid.innerHTML = '';
                        data.data.forEach(s => {
                            const card = document.createElement('div');
                            card.className = 'card';
                            card.onclick = () => showSeries(s.slug);
                            card.innerHTML = `
                                <div class="card-poster">
                                    <img src="${s.poster_url}" alt="" onerror="this.src='https://via.placeholder.com/200x290?text=${encodeURIComponent(s.title)}'">
                                </div>
                                <div class="card-body">
                                    <div class="card-title">${s.title}</div>
                                    <div class="card-sub">Diziyi Aç</div>
                                </div>
                            `;
                            grid.appendChild(card);
                        });
                    });
            } else if (tab === 'docs') {
                title.innerText = '📖 Dizibox REST API Uç Noktaları';
                grid.innerHTML = `
                    <div style="grid-column: 1 / -1; background:#151922; padding:20px; border-radius:8px; border:1px solid #21262d;">
                        <h4 style="margin-bottom:12px; color:#e50914;">Kullanılabilir JSON API Uç Noktaları:</h4>
                        <ul style="line-height:2; font-size:14px; list-style-position:inside;">
                            <li><code>GET /api/recent?page=1</code> - Son eklenen güncel bölümler</li>
                            <li><code>GET /api/search?q={query}</code> - Dizi arama (4800+ yapım)</li>
                            <li><code>GET /api/series/{slug}</code> - Dizi detayları, oyuncular ve tüm bölümler</li>
                            <li><code>GET /api/stream/{episode_slug}</code> - MolySTREAM deşifresi & HLS m3u8 akışı</li>
                            <li><code>GET /api/archive?page=1</code> - Dizi arşivi listesi</li>
                            <li><code>GET /api/cache/stats</code> - TTL önbellek performans metrikleri</li>
                        </ul>
                    </div>
                `;
            }
        }

        function searchSeries() {
            const q = document.getElementById('searchInput').value.trim();
            if (!q) return;
            const grid = document.getElementById('mainGrid');
            const title = document.getElementById('secTitle');
            title.innerText = `🔍 Arama Sonuçları: "${q}"`;
            grid.innerHTML = '<p style="color:#8b949e">Aranıyor...</p>';

            fetch('/api/search?q=' + encodeURIComponent(q))
                .then(r => r.json())
                .then(data => {
                    grid.innerHTML = '';
                    if (!data.data || data.data.length === 0) {
                        grid.innerHTML = '<p style="color:#8b949e">Sonuç bulunamadı.</p>';
                        return;
                    }
                    data.data.forEach(s => {
                        const card = document.createElement('div');
                        card.className = 'card';
                        card.onclick = () => showSeries(s.slug);
                        card.innerHTML = `
                            <div class="card-poster">
                                <img src="${s.poster_url}" onerror="this.src='https://via.placeholder.com/200x290?text=${encodeURIComponent(s.title)}'">
                            </div>
                            <div class="card-body">
                                <div class="card-title">${s.title}</div>
                                <div class="card-sub">Diziyi Aç</div>
                            </div>
                        `;
                        grid.appendChild(card);
                    });
                });
        }

        function showSeries(slug) {
            const modal = document.getElementById('modalOverlay');
            const title = document.getElementById('modalTitle');
            const body = document.getElementById('modalBody');
            modal.style.display = 'flex';
            title.innerText = 'Dizi Yükleniyor...';
            body.innerHTML = '<p style="color:#8b949e">Bölümler ve detaylar çekiliyor...</p>';

            fetch('/api/series/' + slug)
                .then(r => r.json())
                .then(res => {
                    if (res.status !== 'success') {
                        body.innerHTML = `<p style="color:#e50914">Hata: ${res.message}</p>`;
                        return;
                    }
                    const s = res.data;
                    title.innerText = s.title;

                    let seasonsHtml = '';
                    if (s.seasons && Object.keys(s.seasons).length > 0) {
                        for (const [seasonNum, eps] of Object.entries(s.seasons)) {
                            let epButtons = '';
                            eps.forEach(ep => {
                                epButtons += `<button class="ep-btn" onclick="playEpisode('${ep.slug}', '${ep.title}')">▶ ${ep.title}</button>`;
                            });
                            seasonsHtml += `
                                <div style="margin-top:16px;">
                                    <div style="font-weight:700; font-size:14px; margin-bottom:8px; color:#e50914;">Sezon ${seasonNum} (${eps.length} Bölüm)</div>
                                    <div class="episodes-grid">${epButtons}</div>
                                </div>
                            `;
                        }
                    } else {
                        let epButtons = '';
                        s.episodes.forEach(ep => {
                            epButtons += `<button class="ep-btn" onclick="playEpisode('${ep.slug}', '${ep.title}')">▶ ${ep.title}</button>`;
                        });
                        seasonsHtml = `<div class="episodes-grid">${epButtons || '<p>Bölüm bulunamadı.</p>'}</div>`;
                    }

                    body.innerHTML = `
                        <div style="display:flex; gap:16px; margin-bottom:16px;">
                            <img src="${s.poster_url}" style="width:120px; border-radius:6px; object-fit:cover;" onerror="this.style.display='none'">
                            <div>
                                <h3 style="margin-bottom:6px;">${s.title}</h3>
                                <p style="color:#8b949e; font-size:13px; margin-bottom:8px;">${s.genres.join(', ') || 'Dizi'}</p>
                                <p style="font-size:13px; line-height:1.4;">${s.description || 'Açıklama bulunamadı.'}</p>
                            </div>
                        </div>
                        <h4 style="margin-top:16px; margin-bottom:8px; border-bottom:1px solid #21262d; padding-bottom:6px;">Tüm Sezonlar & Bölümler (${s.total_episodes} Bölüm)</h4>
                        ${seasonsHtml}
                    `;
                });
        }

        function playEpisode(slug, epTitle) {
            const modal = document.getElementById('modalOverlay');
            const title = document.getElementById('modalTitle');
            const body = document.getElementById('modalBody');
            modal.style.display = 'flex';
            title.innerText = epTitle || slug;
            body.innerHTML = '<p style="color:#8b949e">MolySTREAM video akışı ve şifresi çözülüyor...</p>';

            fetch('/api/stream/' + slug)
                .then(r => r.json())
                .then(res => {
                    if (res.status !== 'success') {
                        body.innerHTML = `<p style="color:#e50914">Hata: ${res.message}</p>`;
                        return;
                    }
                    const stream = res.data;
                    const m3u8Src = stream.proxied_m3u8_url || `/api/m3u8/${slug}`;
                    const embedPageUrl = `/api/embed/${slug}`;
                    body.innerHTML = `
                        <div class="video-wrapper">
                            <video id="dizibox-video" class="video-js vjs-default-skin vjs-big-play-centered" controls autoplay playsinline preload="auto">
                                <source src="${m3u8Src}" type="application/x-mpegURL">
                            </video>
                        </div>
                        <div style="display:flex; justify-content:space-between; align-items:center; background:#11141c; padding:12px; border-radius:6px; font-size:12px; border:1px solid #21262d; margin-top:10px;">
                            <div>
                                <p><strong>HLS M3U8 Akışı:</strong> <a href="${m3u8Src}" target="_blank" style="color:#58a6ff;">${m3u8Src}</a></p>
                                <p style="color:#8b949e; font-size:11px; margin-top:4px;">Doğrudan MolySTREAM URL: <a href="${stream.stream_url}" target="_blank" style="color:#8b949e;">${stream.stream_url}</a></p>
                            </div>
                            <a href="${embedPageUrl}" target="_blank" style="background:#e50914; color:#fff; text-decoration:none; padding:6px 12px; border-radius:4px; font-weight:600; font-size:12px;">Yeni Sekmede Aç ↗</a>
                        </div>
                    `;
                    if (playerInstance) {
                        try { playerInstance.dispose(); } catch(e){}
                    }
                    playerInstance = videojs('dizibox-video', {
                        fluid: false,
                        liveui: false
                    });
                });
        }

        function closeModal() {
            document.getElementById('modalOverlay').style.display = 'none';
            if (playerInstance) {
                try { playerInstance.dispose(); } catch(e){}
                playerInstance = null;
            }
        }
    </script>
</body>
</html>
"""


@app.route("/", methods=["GET"])
def index():
    """Render interactive cinema web dashboard."""
    return render_template_string(INDEX_HTML)


if __name__ == "__main__":
    port = 5000
    print(f"[*] Dizibox REST API & Web Dashboard: http://localhost:{port}")
    try:
        from waitress import serve
        print("[*] Üretim WSGI Sunucusu başlatılıyor (Waitress, 8 iş parçacığı)...")
        serve(app, host="0.0.0.0", port=port, threads=8)
    except ImportError:
        print("[!] Waitress bulunamadı, dahili Flask sunucusu başlatılıyor...")
        app.run(host="0.0.0.0", port=port, threaded=True, debug=False)
