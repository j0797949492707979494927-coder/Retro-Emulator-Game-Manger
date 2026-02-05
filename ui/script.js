window.lastGameUrl = "";

async function doSearch() {
    const q = document.getElementById("search").value;
    const res = await fetch(`/search?q=${encodeURIComponent(q)}`);
    const data = await res.json();
    const container = document.getElementById("games");

    container.innerHTML = "";

    if (!data.games || data.games.length === 0) {
        container.innerHTML = "<p>No games found.</p>";
        return;
    }

    // -----------------------------
    // Group games by console
    const grouped = {};
    for (const game of data.games) {
        const key = game.console || "Other";
        if (!grouped[key]) grouped[key] = [];
        grouped[key].push(game);
    }

    // -----------------------------
    // Render each console section
    for (const consoleName in grouped) {
        // Section wrapper
        const section = document.createElement("div");
        section.className = "console-section";

        // Console title
        const header = document.createElement("h2");
        header.className = "console-header";
        header.textContent = consoleName;
        section.appendChild(header);

        // Game grid
        const grid = document.createElement("div");
        grid.className = "console-grid";

        for (const game of grouped[consoleName]) {
            const div = document.createElement("div");
            div.className = "game";

            div.innerHTML = `
                <img src="${game.thumbnail ? `/proxy_image?url=${encodeURIComponent(game.thumbnail)}` : 'placeholder.png'}">
                <div class="title">${game.title}</div>
                <div class="platform">
                    ${game.players ? game.players : ""}
                </div>
            `;

            div.onclick = () => showGame(game.link);
            grid.appendChild(div);
        }

        section.appendChild(grid);
        container.appendChild(section);
    }
}


async function showGame(url) {
    window.lastGameUrl = url;
    const res = await fetch(`/game?url=${encodeURIComponent(url)}`);
    const data = await res.json();
    const game = data.game;
    const container = document.getElementById("games");
    container.innerHTML = `<h2>${game.title}</h2>`;

    // Screenshots
    if(game.screenshots.length){
        const ssDiv = document.createElement("div");
        ssDiv.style.display = "flex";
        ssDiv.style.gap = "10px";
        game.screenshots.forEach(ss => {
    const img = document.createElement("img");
    img.src = `/proxy_image?url=${encodeURIComponent(ss)}`;
    img.style.height = "120px";
    ssDiv.appendChild(img);
});

        container.appendChild(ssDiv);
    }

    // Info
    const infoDiv = document.createElement("div");
    infoDiv.style.margin = "10px 0";
    for(const key in game.info){
        const p = document.createElement("p");
        p.textContent = `${key}: ${game.info[key]}`;
        infoDiv.appendChild(p);
    }
    container.appendChild(infoDiv);

    // Downloads
    game.downloads.forEach(rom => {
        const div = document.createElement("div");
        div.style.marginBottom = "10px";
        if(rom.local){
            div.innerHTML = `${rom.name} - <button onclick="deleteROM('${rom.name}', '${rom.path.split('/')[2]}')">Delete</button>`;
        } else {
            div.innerHTML = `${rom.name} - <button onclick="downloadROM('${rom.download_url}')">Download</button>`;
        }
        container.appendChild(div);
    });
}

async function downloadROM(url){
    await fetch(url);
    showGame(window.lastGameUrl);
}

async function deleteROM(name, console){
    await fetch(`/delete?filename=${encodeURIComponent(name)}&console=${encodeURIComponent(console)}`);
    showGame(window.lastGameUrl);
}

// Console menu navigation
document.querySelectorAll("#consoleMenu .item").forEach(item=>{
    item.onclick = ()=>{
        document.querySelectorAll("#consoleMenu .item").forEach(i=>i.classList.remove("active"));
        item.classList.add("active");
    };
});


// Track selected console
let selectedConsole = null;

document.querySelectorAll("#consoleMenu .item").forEach(item=>{
    item.onclick = ()=>{
        document.querySelectorAll("#consoleMenu .item").forEach(i=>i.classList.remove("active"));
        item.classList.add("active");
        selectedConsole = item.getAttribute("data-console");
        loadLocalGames(selectedConsole);
    };
});

// Load local ROMs for a console
async function loadLocalGames(console){
    const res = await fetch(`/roms/${console}/`);
    const container = document.getElementById("games");
    container.innerHTML = `<h2>${console.toUpperCase()} - Local Games</h2>`;
    
    // Since Flask cannot list directories via /roms/, we'll fetch from backend API
    const apiRes = await fetch(`/list_console?console=${console}`);
    const data = await apiRes.json();
    if(!data.roms || data.roms.length === 0){
        container.innerHTML += "<p>No games downloaded yet.</p>";
        return;
    }

    data.roms.forEach(name=>{
        const div = document.createElement("div");
        div.className = "game";
        div.innerHTML = `
            <div class="title">${name}</div>
            <button onclick="deleteROM('${name}','${console}')">Delete</button>
        `;
        container.appendChild(div);
    });
}
