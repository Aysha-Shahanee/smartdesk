// SmartDesk Browser Extension — Options Page Script
// Reads/writes config to chrome.storage.sync

document.addEventListener("DOMContentLoaded", () => {
    const userIdInput = document.getElementById("userId");
    const backendUrlInput = document.getElementById("backendUrl");
    const saveBtn = document.getElementById("saveBtn");
    const statusEl = document.getElementById("status");

    // Load saved settings
    chrome.storage.sync.get({
        userId: "",
        backendUrl: "http://127.0.0.1:8000"
    }, (config) => {
        userIdInput.value = config.userId || "";
        backendUrlInput.value = config.backendUrl || "http://127.0.0.1:8000";
    });

    // Save settings
    saveBtn.addEventListener("click", () => {
        const userId = userIdInput.value.trim();
        const backendUrl = backendUrlInput.value.trim() || "http://127.0.0.1:8000";

        chrome.storage.sync.set({ userId, backendUrl }, () => {
            statusEl.textContent = "✓ Settings saved!";
            setTimeout(() => { statusEl.textContent = ""; }, 3000);
        });
    });
});
