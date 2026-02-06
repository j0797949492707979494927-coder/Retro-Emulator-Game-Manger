from flask import Flask, jsonify, request, send_from_directory
from bs4 import BeautifulSoup
import json
import os, re, shutil, threading, urllib.parse, uuid, requests

app = Flask(__name__, static_folder="ui", static_url_path="")

ROM_DIR = "roms"
os.makedirs(ROM_DIR, exist_ok=True)
ADDONS_DIR = "addons"
os.makedirs(ADDONS_DIR, exist_ok=True)

THEGAMESDB_HEADERS = {"User-Agent": "Mozilla/5.0 (GameScraper/1.0)"}
THEGAMESDB_PLATFORMS = {
    "dendy": "7",
    "snes": "6",
    "n64": "3",
    "ps1": "10",
    "gba": "5",
}

def has_cover_metadata(metadata):
    if not metadata:
        return False
    return bool(metadata.get("cover_front") or metadata.get("clearlogo"))

download_jobs = {}

# ------------------------------
# Helper: GET with user-agent
def curl_get(url):
    headers = {"User-Agent": "Mozilla/5.0"}
    return requests.get(url, headers=headers).text

# ------------------------------
# Helper: fix URLs for images
def safe_url(url):
    if not url:
        return None
    if url.startswith("//"):
        url = "https:" + url
    # Do NOT quote the path, just return as-is
    return url

# ------------------------------
# Search page parser (corrected)
def parse_search(html):
    soup = BeautifulSoup(html, "html.parser")
    games = []

    for container in soup.select(".fcontainer"):
        # ----- Extract console/handheld/arcade info -----
        header_links = container.select(".fheader a")
        console = None
        console_slug = None

        if header_links:
            # Ignore the first "Consoles"/"Handhelds"/"Arcade"
            for link in header_links[1:]:
                text = link.text.strip()
                href = link.get("href", "")
                if "/roms" in href or "/games" in href:
                    # Stop at the ROMs / Games link
                    break
                console = text
                m = re.search(r"/(consoles|portable|arcade)/([^/]+)", href)
                if m:
                    console_slug = m.group(2)

        # Fallback if console not found
        if not console:
            console = "Other"
        if not console_slug:
            console_slug = "other"

        # ----- Each game inside this console -----
        for p in container.select(".fllinks p"):
            link_node = p.select_one("a")
            img_node = p.select_one("img.preview")
            small_nodes = p.select("small")

            if not link_node:
                continue

            # Image
            thumbnail_url = None
            if img_node and img_node.get("src"):
                src = img_node["src"]
                if src.startswith("//"):
                    thumbnail_url = "https:" + src
                elif src.startswith("/"):
                    thumbnail_url = "https://www.emu-land.net" + src
                else:
                    thumbnail_url = src

            # Genre & players from <small> tags (if available)
            genre = small_nodes[0].text.replace("|", "").strip() if len(small_nodes) > 0 else None
            players = small_nodes[1].text.replace("|", "").strip() if len(small_nodes) > 1 else None

            games.append({
                "title": link_node.text.strip(),
                "link": "https://www.emu-land.net" + link_node.get("href"),
                "thumbnail": thumbnail_url,
                "console": console,
                "console_id": console_slug,
                "genre": genre,
                "players": players
            })

    return games




# ------------------------------
# Game page parser
def parse_game(html, url):
    soup = BeautifulSoup(html, "html.parser")
    title_node = soup.select_one(".rheader h1")
    info_nodes = soup.select("ul.finfo li")
    screenshots = [safe_url(a.get("href")) for a in soup.select(".ss-area .item a") if a.get("href")]
    description = None
    for selector in (".fdesc", ".rdesc", ".description", "#description", ".rtext"):
        desc_node = soup.select_one(selector)
        if desc_node:
            description = " ".join(desc_node.get_text(" ", strip=True).split())
            if description:
                break

    game = {
        "title": title_node.text.strip() if title_node else None,
        "info": {},
        "screenshots": screenshots,
        "downloads": [],
        "description": description
    }

    # Info fields
    for li in info_nodes:
        text = " ".join(li.text.split())
        if "Genre:" in text: game["info"]["genre"] = text.replace("Genre:","").strip()
        if "Players:" in text: game["info"]["players"] = text.replace("Players:","").strip()
        if "Developer:" in text: game["info"]["developer"] = text.replace("Developer:","").strip()
        if "Year of release:" in text: game["info"]["year"] = text.replace("Year of release:","").strip()
        if "Published:" in text: game["info"]["publisher"] = text.replace("Published:","").strip()

    # Extract console/category & game ID
    console_match = re.search(r"/(consoles|portable|arcade)/([^/]+)/roms", url)
    if console_match:
        category = console_match.group(1)
        console = console_match.group(2)
    else:
        category = "consoles"
        console = "misc"

    id_match = re.search(r"id=(\d+)", html)
    if not id_match:
        id_match = re.search(r"-(\d+)$", url)
    game_id = id_match.group(1) if id_match else None

    folder = os.path.join(ROM_DIR, console)
    os.makedirs(folder, exist_ok=True)

    # Fetch ROM download links
    if game_id:
        mfl_url = f"https://www.emu-land.net/en/{category}/{console}/roms?act=getmfl&id={game_id}"
        mfl_html = curl_get(mfl_url)
        soup_dl = BeautifulSoup(mfl_html, "html.parser")
        for a in soup_dl.select(".file a"):
            rom_name = a.text.strip()
            local_path = os.path.join(folder, rom_name)
            if os.path.isfile(local_path):
                game["downloads"].append({
                    "name": rom_name,
                    "local": True,
                    "path": f"/roms/{console}/{urllib.parse.quote(rom_name)}"
                })
            else:
                rom_url = "https://www.emu-land.net" + a.get("href")
                game["downloads"].append({
                    "name": rom_name,
                    "local": False,
                    "download_url": f"/download?url={urllib.parse.quote(rom_url)}&filename={urllib.parse.quote(rom_name)}&console={console}&game_url={urllib.parse.quote(url)}"
                })

    return game

def sanitize_filename(name):
    return os.path.basename(name).replace(os.sep, "_")

def load_local_metadata(metadata_path):
    if not os.path.isfile(metadata_path):
        return None
    try:
        with open(metadata_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return None

def download_screenshot(url, folder, index):
    if not url:
        return None
    parsed = urllib.parse.urlparse(url)
    filename = os.path.basename(parsed.path) or f"screenshot-{index}.jpg"
    filename = sanitize_filename(filename)
    file_path = os.path.join(folder, filename)
    try:
        with requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, stream=True) as r:
            r.raise_for_status()
            with open(file_path, "wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
    except requests.RequestException:
        return None
    return filename

def scrape_thegamesdb_details(game_url):
    r = requests.get(game_url, headers=THEGAMESDB_HEADERS, timeout=10)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    data = {
        "title": "",
        "alternate_title": "",
        "overview": "",
        "platform": "",
        "region": "",
        "developer": "",
        "publisher": "",
        "release_date": "",
        "players": "",
        "coop": "",
        "esrb_rating": "",
        "genres": [],
        "cover_front": "",
        "cover_back": "",
        "fanart": [],
        "clearlogo": "",
        "url": game_url
    }

    title_elem = soup.select_one(".card-header h1")
    if title_elem:
        data["title"] = title_elem.text.strip()

    alt_title_elem = soup.select_one(".card-header h6.text-muted")
    if alt_title_elem:
        alt_text = alt_title_elem.text.strip()
        if "Also know as:" in alt_text:
            data["alternate_title"] = alt_text.replace("Also know as:", "").strip()

    overview_elem = soup.select_one("p.game-overview")
    if overview_elem:
        data["overview"] = overview_elem.text.strip()

    for body in soup.select(".card-body"):
        for p in body.find_all("p"):
            text = p.text.strip()
            if text.startswith("Platform:"):
                platform_link = p.find("a")
                data["platform"] = platform_link.text.strip() if platform_link else ""
            elif text.startswith("Region:"):
                data["region"] = text.replace("Region:", "").strip()
            elif text.startswith("Developer(s):"):
                dev_link = p.find("a")
                data["developer"] = dev_link.text.strip() if dev_link else ""
            elif text.startswith("Publishers(s):"):
                pub_link = p.find("a")
                data["publisher"] = pub_link.text.strip() if pub_link else ""
            elif text.startswith("ReleaseDate:"):
                data["release_date"] = text.replace("ReleaseDate:", "").strip()
            elif text.startswith("Players:"):
                data["players"] = text.replace("Players:", "").strip()
            elif text.startswith("Co-op:"):
                data["coop"] = text.replace("Co-op:", "").strip()
            elif text.startswith("ESRB Rating:"):
                data["esrb_rating"] = text.replace("ESRB Rating:", "").strip()
            elif text.startswith("Genre(s):"):
                genres_text = text.replace("Genre(s):", "").strip()
                data["genres"] = [g.strip() for g in genres_text.split("|") if g.strip()]

    front_cover = soup.select_one('a[data-caption="Front Cover"]')
    if front_cover and front_cover.get("href"):
        data["cover_front"] = front_cover["href"]

    back_cover = soup.select_one('a[data-caption="Back Cover"]')
    if back_cover and back_cover.get("href"):
        data["cover_back"] = back_cover["href"]

    for fanart in soup.select('a[data-fancybox="fanarts"]'):
        if fanart.get("href"):
            data["fanart"].append(fanart["href"])

    clearlogo = soup.select_one('a[data-fancybox="clearlogos"]')
    if clearlogo and clearlogo.get("href"):
        data["clearlogo"] = clearlogo["href"]

    return data

def search_thegamesdb(name, platform_id=None, limit=5):
    params = {"name": name}
    if platform_id:
        params["platform_id[]"] = [platform_id]
    r = requests.get("https://thegamesdb.net/search.php", headers=THEGAMESDB_HEADERS, params=params, timeout=10)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    results = []
    for a in soup.select("a[href*='game.php?id=']")[:limit]:
        game_id = a["href"].split("id=")[-1]
        title_el = a.select_one(".card-footer p")
        results.append({
            "id": game_id,
            "title": title_el.text.strip() if title_el else "No title",
            "url": f"https://thegamesdb.net/game.php?id={game_id}"
        })
    return results

def get_thegamesdb_cover(title, console_id=None):
    platform_id = THEGAMESDB_PLATFORMS.get(console_id)
    results = search_thegamesdb(title, platform_id=platform_id, limit=1)
    if not results:
        return None
    details = scrape_thegamesdb_details(results[0]["url"])
    return details.get("cover_front") or details.get("clearlogo")

def download_asset(url, folder, prefix):
    if not url:
        return None
    parsed = urllib.parse.urlparse(url)
    filename = os.path.basename(parsed.path) or f"{prefix}.jpg"
    filename = sanitize_filename(filename)
    file_path = os.path.join(folder, filename)
    try:
        with requests.get(url, headers=THEGAMESDB_HEADERS, stream=True, timeout=10) as r:
            r.raise_for_status()
            with open(file_path, "wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
    except requests.RequestException:
        return None
    return filename

def merge_metadata(existing, incoming):
    merged = dict(existing or {})

    def replace_if_longer(key, incoming_key=None):
        src_key = incoming_key or key
        incoming_value = (incoming or {}).get(src_key)
        if not incoming_value:
            return
        current_value = merged.get(key, "")
        if len(str(incoming_value)) > len(str(current_value or "")):
            merged[key] = incoming_value
        elif not current_value:
            merged[key] = incoming_value

    replace_if_longer("description", "overview")
    replace_if_longer("overview")

    for key in ("title", "alternate_title", "platform", "region", "developer",
                "publisher", "release_date", "players", "coop", "esrb_rating", "url"):
        if not merged.get(key) and (incoming or {}).get(key):
            merged[key] = incoming[key]

    merged["genres"] = sorted(set((merged.get("genres") or []) + (incoming or {}).get("genres", [])))

    for key in ("cover_front", "cover_back", "clearlogo"):
        if not merged.get(key) and (incoming or {}).get(key):
            merged[key] = incoming[key]

    merged["fanart"] = list(dict.fromkeys((merged.get("fanart") or []) + (incoming or {}).get("fanart", [])))
    return merged

def enrich_metadata(game_folder, base_name, console_id, seed_title=None):
    metadata_path = os.path.join(game_folder, "metadata.json")
    existing = load_local_metadata(metadata_path) or {}
    title = seed_title or existing.get("title") or base_name
    platform_id = THEGAMESDB_PLATFORMS.get(console_id)
    try:
        results = search_thegamesdb(title, platform_id=platform_id, limit=1)
    except requests.RequestException:
        return existing
    if not results:
        return existing

    try:
        incoming = scrape_thegamesdb_details(results[0]["url"])
    except requests.RequestException:
        return existing

    merged = merge_metadata(existing, incoming)
    assets_dir = os.path.join(game_folder, "assets")
    os.makedirs(assets_dir, exist_ok=True)

    for key, prefix in (("cover_front", "cover-front"), ("cover_back", "cover-back"), ("clearlogo", "clearlogo")):
        url = merged.get(key)
        if url:
            filename = download_asset(url, assets_dir, prefix)
            if filename:
                merged[key] = f"/roms/{console_id}/{base_name}/assets/{filename}"

    fanart_local = []
    for index, url in enumerate(merged.get("fanart", []), start=1):
        filename = download_asset(url, assets_dir, f"fanart-{index}")
        if filename:
            fanart_local.append(f"/roms/{console_id}/{base_name}/assets/{filename}")
    if fanart_local:
        merged["fanart"] = fanart_local

    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    return merged

def refresh_missing_covers(target_console=None):
    updated = 0
    skipped = 0
    consoles = [target_console] if target_console else os.listdir(ROM_DIR)
    for console_id in consoles:
        console_path = os.path.join(ROM_DIR, console_id)
        if not os.path.isdir(console_path):
            continue
        for entry in os.listdir(console_path):
            entry_path = os.path.join(console_path, entry)
            if not os.path.isdir(entry_path):
                continue
            metadata_path = os.path.join(entry_path, "metadata.json")
            metadata = load_local_metadata(metadata_path)
            if has_cover_metadata(metadata):
                skipped += 1
                continue
            enrich_metadata(entry_path, entry, console_id, seed_title=(metadata or {}).get("title"))
            updated += 1
    return {"updated": updated, "skipped": skipped}

def list_consoles():
    if not os.path.isdir(ROM_DIR):
        return []
    return sorted([name for name in os.listdir(ROM_DIR) if os.path.isdir(os.path.join(ROM_DIR, name))])

def run_download_job(job_id, rom_url, rom_name, console, game_url):
    download_jobs[job_id]["status"] = "downloading"
    try:
        folder = os.path.join(ROM_DIR, console)
        os.makedirs(folder, exist_ok=True)
        safe_rom_name = sanitize_filename(rom_name)
        base_name = os.path.splitext(safe_rom_name)[0]
        game_folder = os.path.join(folder, base_name)
        os.makedirs(game_folder, exist_ok=True)
        file_path = os.path.join(game_folder, safe_rom_name)

        if not os.path.isfile(file_path):
            with requests.get(rom_url, headers={"User-Agent": "Mozilla/5.0"}, stream=True) as r:
                r.raise_for_status()
                with open(file_path, "wb") as f:
                    for chunk in r.iter_content(8192):
                        f.write(chunk)

        if game_url:
            try:
                html = curl_get(game_url)
                game_data = parse_game(html, game_url)
            except requests.RequestException:
                game_data = None

            if game_data:
                metadata_path = os.path.join(game_folder, "metadata.json")
                screenshots_dir = os.path.join(game_folder, "screenshots")
                os.makedirs(screenshots_dir, exist_ok=True)

                local_screenshots = []
                for index, screenshot_url in enumerate(game_data.get("screenshots", []), start=1):
                    filename = download_screenshot(screenshot_url, screenshots_dir, index)
                    if filename:
                        local_screenshots.append(f"/roms/{console}/{base_name}/screenshots/{filename}")

                metadata = {
                    "rom": safe_rom_name,
                    "title": game_data.get("title"),
                    "info": game_data.get("info", {}),
                    "description": game_data.get("description"),
                    "screenshots": local_screenshots,
                    "source_url": game_url
                }
                existing_metadata = load_local_metadata(metadata_path) or {}
                merged = merge_metadata(existing_metadata, metadata)
                with open(metadata_path, "w", encoding="utf-8") as f:
                    json.dump(merged, f, ensure_ascii=False, indent=2)
                enrich_metadata(game_folder, base_name, console, seed_title=merged.get("title"))
        download_jobs[job_id]["status"] = "complete"
    except requests.RequestException as exc:
        download_jobs[job_id]["status"] = "error"
        download_jobs[job_id]["error"] = str(exc)



@app.after_request
def apply_shared_array_buffer_headers(response):
    # Required for cores that depend on SharedArrayBuffer (e.g. PPSSPP via EmulatorJS).
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
    return response

# ------------------------------
# Routes
@app.route("/")
def index():
    return send_from_directory("ui", "index.html")

@app.route("/search")
def search():
    q = request.args.get("q", "").strip()
    url = f"https://www.emu-land.net/en/search_games?id=all&genre=--&players=--&q={q}"
    html = curl_get(url)
    games = parse_search(html)
    return jsonify({"status":"ok","games":games})

@app.route("/game")
def game_page():
    url = request.args.get("url")
    if not url:
        return jsonify({"status":"error","message":"Missing URL"}), 400
    html = curl_get(url)
    game = parse_game(html, url)
    return jsonify({"status":"ok","game":game})

@app.route("/download")
def download_rom():
    rom_url = request.args.get("url")
    rom_name = request.args.get("filename")
    console = request.args.get("console", "misc")
    game_url = request.args.get("game_url")
    if not rom_url or not rom_name:
        return jsonify({"error": "Missing parameters"}), 400
    job_id = str(uuid.uuid4())
    download_jobs[job_id] = {"status": "queued", "error": None}
    thread = threading.Thread(
        target=run_download_job,
        args=(job_id, rom_url, rom_name, console, game_url),
        daemon=True
    )
    thread.start()
    return jsonify({"success": True, "job_id": job_id})

@app.route("/delete")
def delete_rom():
    rom_name = request.args.get("filename")
    console = request.args.get("console", "misc")
    game_dir = request.args.get("game")
    if game_dir:
        folder_path = os.path.join(ROM_DIR, console, sanitize_filename(game_dir))
        if os.path.isdir(folder_path):
            shutil.rmtree(folder_path)
            return jsonify({"success": True})
        return jsonify({"error":"Folder not found"}), 404
    if rom_name:
        file_path = os.path.join(ROM_DIR, console, rom_name)
        if os.path.isfile(file_path):
            os.remove(file_path)
            return jsonify({"success": True})
    return jsonify({"error":"File not found"}), 404

@app.route("/roms/<console>/<path:filename>")
def serve_rom(console, filename):
    return send_from_directory(os.path.join(ROM_DIR, console), filename)

@app.route("/Icons/<path:filename>")
def serve_icons(filename):
    return send_from_directory("Icons", filename)

@app.route("/<path:path>")
def static_files(path):
    return send_from_directory("ui", path)

@app.route("/list_console")
def list_console():
    console = request.args.get("console", "misc")
    folder = os.path.join(ROM_DIR, console)
    if not os.path.isdir(folder):
        return jsonify({"roms": [], "games": []})
    roms = [f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f))]
    games = []
    for entry in sorted(os.listdir(folder)):
        entry_path = os.path.join(folder, entry)
        if not os.path.isdir(entry_path):
            continue
        metadata_path = os.path.join(entry_path, "metadata.json")
        metadata = load_local_metadata(metadata_path)
        rom_files = [f for f in os.listdir(entry_path) if os.path.isfile(os.path.join(entry_path, f)) and not f.endswith(".json")]
        rom_file = rom_files[0] if rom_files else None
        games.append({
            "folder": entry,
            "rom": rom_file,
            "title": (metadata or {}).get("title") or entry,
            "description": (metadata or {}).get("description"),
            "overview": (metadata or {}).get("overview"),
            "info": (metadata or {}).get("info") or {},
            "screenshots": (metadata or {}).get("screenshots") or [],
            "cover_front": (metadata or {}).get("cover_front"),
            "cover_back": (metadata or {}).get("cover_back"),
            "fanart": (metadata or {}).get("fanart") or [],
            "clearlogo": (metadata or {}).get("clearlogo")
        })
    return jsonify({"roms": roms, "games": games})

@app.route("/list_consoles")
def list_consoles_route():
    return jsonify({"consoles": list_consoles()})

@app.route("/refresh_covers")
def refresh_covers():
    console = request.args.get("console")
    results = refresh_missing_covers(console)
    return jsonify({"status": "ok", **results})

@app.route("/download_status")
def download_status():
    job_id = request.args.get("job_id")
    if not job_id or job_id not in download_jobs:
        return jsonify({"status": "error", "message": "Unknown job"}), 404
    return jsonify({"status": "ok", "job": download_jobs[job_id]})

@app.route("/market_cover")
def market_cover():
    title = request.args.get("title")
    console = request.args.get("console")
    if not title:
        return jsonify({"status": "error", "message": "Missing title"}), 400
    try:
        cover = get_thegamesdb_cover(title, console_id=console)
    except requests.RequestException:
        cover = None
    return jsonify({"status": "ok", "cover": cover})

@app.route("/addons")
def list_addons():
    addons = []
    for name in sorted(os.listdir(ADDONS_DIR)):
        if os.path.isdir(os.path.join(ADDONS_DIR, name)):
            addons.append(name)
    return jsonify({"addons": addons})

@app.route("/proxy_image")
def proxy_image():
    img_url = request.args.get("url")
    if not img_url:
        return "Missing URL", 400

    img_url = safe_url(img_url)  # <-- use safe_url here too

    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(img_url, headers=headers, stream=True)
    if r.status_code != 200:
        return "Image not found", 404

    content_type = r.headers.get("Content-Type", "image/jpeg")
    return r.content, 200, {"Content-Type": content_type}
