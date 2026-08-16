// SmartDesk browser extension — popup.js

const DEFAULT = {
  backendUrl: "http://127.0.0.1:8000",
  userId: "local_user",
  enabled: true,
};

async function load() {
  const stored = await chrome.storage.local.get(Object.keys(DEFAULT));
  const cfg = { ...DEFAULT, ...stored };

  document.getElementById("backendUrl").value = cfg.backendUrl;
  document.getElementById("userId").value = cfg.userId;
  document.getElementById("enabled").checked = cfg.enabled;

  await updateStatus(cfg);
}

async function updateStatus(cfg) {
  const dot = document.getElementById("statusDot");
  const bar = document.getElementById("statusBar");

  if (!cfg.enabled) {
    dot.className = "dot off";
    bar.textContent = "Tracking disabled";
    return;
  }

  try {
    const res = await fetch(`${cfg.backendUrl}/health/`, {
      signal: AbortSignal.timeout(3000),
    });
    if (res.ok) {
      dot.className = "dot";
      bar.textContent = `Connected — ${cfg.backendUrl}`;
    } else {
      throw new Error(`HTTP ${res.status}`);
    }
  } catch {
    dot.className = "dot off";
    bar.textContent = "Backend unreachable";
  }
}

document.getElementById("saveBtn").addEventListener("click", async () => {
  const cfg = {
    backendUrl: document.getElementById("backendUrl").value.trim().replace(/\/$/, ""),
    userId: document.getElementById("userId").value.trim() || "local_user",
    enabled: document.getElementById("enabled").checked,
  };
  await chrome.storage.local.set(cfg);
  document.getElementById("statusBar").textContent = "Saved!";
  setTimeout(() => updateStatus(cfg), 800);
});

load();
