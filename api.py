from flask import Flask, jsonify, request, send_from_directory
from bs4 import BeautifulSoup
import json
import os, re, urllib.parse, requests

app = Flask(__name__, static_folder="ui", static_url_path="")

ROM_DIR = "roms"
os.makedirs(ROM_DIR, exist_ok=True)

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

    folder = os.path.join(ROM_DIR, console)
    os.makedirs(folder, exist_ok=True)
    safe_rom_name = sanitize_filename(rom_name)
    file_path = os.path.join(folder, safe_rom_name)

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
            base_name = os.path.splitext(safe_rom_name)[0]
            metadata_path = os.path.join(folder, f"{base_name}.json")
            screenshots_dir = os.path.join(folder, f"{base_name}_screenshots")
            os.makedirs(screenshots_dir, exist_ok=True)

            local_screenshots = []
            for index, screenshot_url in enumerate(game_data.get("screenshots", []), start=1):
                filename = download_screenshot(screenshot_url, screenshots_dir, index)
                if filename:
                    local_screenshots.append(f"/roms/{console}/{os.path.basename(screenshots_dir)}/{filename}")

            metadata = {
                "rom": safe_rom_name,
                "title": game_data.get("title"),
                "info": game_data.get("info", {}),
                "description": game_data.get("description"),
                "screenshots": local_screenshots,
                "source_url": game_url
            }
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
    return jsonify({"success": True})

@app.route("/delete")
def delete_rom():
    rom_name = request.args.get("filename")
    console = request.args.get("console", "misc")
    file_path = os.path.join(ROM_DIR, console, rom_name)
    if os.path.isfile(file_path):
        os.remove(file_path)
        return jsonify({"success": True})
    return jsonify({"error":"File not found"}), 404

@app.route("/roms/<console>/<path:filename>")
def serve_rom(console, filename):
    return send_from_directory(os.path.join(ROM_DIR, console), filename)

@app.route("/<path:path>")
def static_files(path):
    return send_from_directory("ui", path)

@app.route("/list_console")
def list_console():
    console = request.args.get("console", "misc")
    folder = os.path.join(ROM_DIR, console)
    if not os.path.isdir(folder):
        return jsonify({"roms":[]})
    roms = [f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder,f))]
    return jsonify({"roms": roms})

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
