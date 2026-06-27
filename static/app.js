// APPLICATION STATE MANAGEMENT
const state = {
    apiKey: "",
    activeRepoPath: ".",
    activeRepoName: "",
    currentFile: "",
    dependencyGraph: null
};

// INITIALIZE APP
document.addEventListener("DOMContentLoaded", () => {
    // Initialize Lucide Icons
    lucide.createIcons();
    
    // Bind Event Listeners
    setupEventHandlers();
    
    // Attempt to read cached key or configurations
    const cachedKey = localStorage.getItem("gemini_api_key");
    if (cachedKey) {
        state.apiKey = cachedKey;
        document.getElementById("api-key-input").value = cachedKey;
    }
    updateAPIButtonState();
});


// EVENT BINDINGS
function setupEventHandlers() {
    // Setup repo scanning
    document.getElementById("scan-btn").addEventListener("click", triggerRepoScan);
    
    // Setup settings modal
    document.getElementById("settings-btn").addEventListener("click", toggleSettingsModal);
    document.getElementById("close-settings-btn").addEventListener("click", toggleSettingsModal);
    document.getElementById("save-settings-btn").addEventListener("click", saveSettings);
    
    // Tab switching
    const tabButtons = document.querySelectorAll(".tab-btn");
    tabButtons.forEach(btn => {
        btn.addEventListener("click", (e) => {
            const tabName = btn.getAttribute("data-tab");
            switchTab(tabName, btn);
        });
    });

    // Chat sending
    document.getElementById("send-btn").addEventListener("click", sendChatMessage);
    document.getElementById("chat-input").addEventListener("keypress", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendChatMessage();
        }
    });

    // Presets actions
    document.getElementById("preset-change-impact").addEventListener("click", openChangeImpactModal);
    document.getElementById("preset-feature-planner").addEventListener("click", openFeaturePlannerModal);
    document.getElementById("preset-architecture").addEventListener("click", openArchitectureModal);
    document.getElementById("preset-pr-review").addEventListener("click", openPRReviewModal);
    
    // Refresh graph
    document.getElementById("refresh-graph-btn").addEventListener("click", loadDependencyGraph);
    
    // Generate Onboarding Tour
    document.getElementById("generate-onboarding-btn").addEventListener("click", generateOnboardingRoadmap);
    
    // Dynamic close button for Action Modal
    document.getElementById("close-action-btn").addEventListener("click", toggleActionModal);
}

// TAB SWITCHING LOGIC
function switchTab(tabId, buttonElement) {
    // Update active tab buttons
    document.querySelectorAll(".tab-btn").forEach(btn => btn.classList.remove("active"));
    buttonElement.classList.add("active");
    
    // Update active content areas
    document.querySelectorAll(".tab-content").forEach(content => content.classList.remove("active"));
    document.getElementById(`tab-${tabId}`).classList.add("active");
    
    // Lazy-load graph or onboarding tour if selected
    if (tabId === "dependency-graph") {
        setTimeout(loadDependencyGraph, 50); // Small timeout to ensure container has sizing
    }
}

// STATUS INDICATOR HELPER
function updateStatus(text, type = "standby") {
    const badge = document.getElementById("status-badge");
    const statusText = badge.querySelector(".status-text");
    
    badge.className = `status-badge ${type}`;
    statusText.textContent = text;
}

// SETTINGS MODAL INTERACTION
function toggleSettingsModal() {
    const modal = document.getElementById("settings-modal");
    modal.classList.toggle("hidden");
}

function saveSettings() {
    const key = document.getElementById("api-key-input").value.trim();
    state.apiKey = key;
    localStorage.setItem("gemini_api_key", key);
    toggleSettingsModal();
    updateAPIButtonState();
    
    // Display status confirmation
    updateStatus("API Configured", "online");
    setTimeout(() => updateStatus("Standby", "online"), 2000);
}

function updateAPIButtonState() {
    const apiBtn = document.getElementById("settings-btn");
    const apiBtnText = document.getElementById("api-btn-text");
    const iconEl = apiBtn.querySelector("i");
    
    if (state.apiKey) {
        apiBtn.classList.remove("api-key-btn-warning");
        apiBtn.classList.add("active");
        apiBtnText.textContent = "API Key Active";
        iconEl.setAttribute("data-lucide", "key-round");
    } else {
        apiBtn.classList.remove("active");
        apiBtn.classList.add("api-key-btn-warning");
        apiBtnText.textContent = "Set API Key";
        iconEl.setAttribute("data-lucide", "key");
    }
    lucide.createIcons();
}


// ACTION MODAL INTERACTION
function toggleActionModal(title = "", contentHTML = "") {
    const modal = document.getElementById("action-modal");
    const modalTitle = document.getElementById("action-modal-title");
    const modalBody = document.getElementById("action-modal-body");
    
    if (title) modalTitle.textContent = title;
    if (contentHTML) modalBody.innerHTML = contentHTML;
    
    modal.classList.toggle("hidden");
    lucide.createIcons();
}

// REPOSITORY SCANNING (TRIGGER & RESPONSE)
async function triggerRepoScan() {
    const pathInput = document.getElementById("repo-path-input").value.trim();
    if (!pathInput) return;
    
    updateStatus("Scanning codebase...", "working");
    document.getElementById("file-tree").innerHTML = '<div class="loading-text">Crawling directories and dependencies...</div>';
    
    try {
        const response = await fetch("/api/scan", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                path: pathInput,
                api_key: state.apiKey
            })
        });
        
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || "Scan failed.");
        }
        
        const data = await response.json();
        
        // Update states
        state.activeRepoPath = data.repo_path;
        state.activeRepoName = data.repo_name;
        
        // Update Header
        document.getElementById("active-repo-name").textContent = data.repo_name;
        document.getElementById("active-repo-path").textContent = data.repo_path;
        
        // Update Usage stats
        updateUsageStats(data.stats);
        
        // Load tree Explorer
        loadDirectoryTree();
        
        updateStatus("Scan complete", "online");
        setTimeout(() => updateStatus("Standby", "online"), 2000);
    } catch (error) {
        alert(`Error: ${error.message}`);
        document.getElementById("file-tree").innerHTML = `<div class="loading-text">Scan error: ${error.message}</div>`;
        updateStatus("Scan Failed", "offline");
    }
}

// UPDATE USAGE METER
function updateUsageStats(stats) {
    if (!stats) return;
    document.getElementById("stat-files-found").textContent = stats.files_total_count || 0;
    
    const indexed = stats.files_indexed_new_count || 0;
    const cached = stats.files_cached_count || 0;
    document.getElementById("stat-files-indexed").textContent = `${indexed} / ${cached}`;
    
    const tokens = (stats.total_prompt_tokens || 0) + (stats.total_candidate_tokens || 0);
    document.getElementById("stat-tokens-used").textContent = formatNumber(tokens);
    
    const cost = stats.total_estimated_cost || 0.0;
    document.getElementById("stat-cost").textContent = `$${cost.toFixed(4)}`;
}

function formatNumber(num) {
    if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
    if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
    return num;
}

// RENDER FOLDER EXPLORER
async function loadDirectoryTree() {
    try {
        const response = await fetch("/api/tree");
        const treeData = await response.json();
        
        const explorerContainer = document.getElementById("file-tree");
        explorerContainer.innerHTML = "";
        
        const rootElement = renderTreeNode(treeData);
        explorerContainer.appendChild(rootElement);
        lucide.createIcons();
    } catch (error) {
        console.error("Failed loading tree:", error);
    }
}

function renderTreeNode(node) {
    const nodeEl = document.createElement("div");
    nodeEl.className = "tree-node";
    
    const itemEl = document.createElement("div");
    itemEl.className = "tree-item";
    
    const iconEl = document.createElement("i");
    iconEl.className = "tree-icon";
    
    if (node.type === "directory") {
        iconEl.setAttribute("data-lucide", "folder");
        itemEl.classList.add("tree-folder");
        
        // Directory collapse/expand toggling
        const childrenContainer = document.createElement("div");
        childrenContainer.className = "tree-children";
        
        itemEl.addEventListener("click", (e) => {
            e.stopPropagation();
            const isCollapsed = childrenContainer.style.display === "none";
            childrenContainer.style.display = isCollapsed ? "block" : "none";
            iconEl.setAttribute("data-lucide", isCollapsed ? "folder-open" : "folder");
            lucide.createIcons();
        });
        
        itemEl.appendChild(iconEl);
        
        const nameText = document.createElement("span");
        nameText.textContent = node.name;
        itemEl.appendChild(nameText);
        
        nodeEl.appendChild(itemEl);
        
        // Append children
        if (node.children) {
            node.children.forEach(child => {
                childrenContainer.appendChild(renderTreeNode(child));
            });
        }
        nodeEl.appendChild(childrenContainer);
    } else {
        iconEl.setAttribute("data-lucide", "file-code-2");
        itemEl.appendChild(iconEl);
        
        const nameText = document.createElement("span");
        nameText.textContent = node.name;
        itemEl.appendChild(nameText);
        
        // Single file click loading
        itemEl.addEventListener("click", (e) => {
            e.stopPropagation();
            
            // Mark active item
            document.querySelectorAll(".tree-item").forEach(el => el.classList.remove("active"));
            itemEl.classList.add("active");
            
            loadFileInspector(node.path);
        });
        
        nodeEl.appendChild(itemEl);
    }
    
    return nodeEl;
}

// FILE INSPECTOR PANEL (LOAD & HIGHLIGHT)
async function loadFileInspector(filePath) {
    state.currentFile = filePath;
    document.getElementById("inspected-filename").textContent = filePath.split('/').pop();
    
    try {
        const response = await fetch(`/api/file?path=${encodeURIComponent(filePath)}`);
        if (!response.ok) throw new Error("File fetch failed.");
        const data = await response.json();
        
        // Render File Metadata Card
        const metaCard = document.getElementById("file-meta-card");
        const noFile = metaCard.querySelector(".no-file-selected");
        const metaContent = metaCard.querySelector(".meta-content");
        
        noFile.classList.add("hidden");
        metaContent.classList.remove("hidden");
        
        // Load metadata fields
        document.getElementById("meta-purpose").textContent = data.metadata.purpose || "No AI summary cached.";
        
        // Populate Tags (Exports)
        const exportsContainer = document.getElementById("meta-exports");
        exportsContainer.innerHTML = "";
        const exports = data.metadata.exports || [];
        if (exports.length > 0) {
            exports.forEach(exp => {
                const tag = document.createElement("span");
                tag.className = "tag";
                tag.textContent = exp;
                exportsContainer.appendChild(tag);
            });
        } else {
            exportsContainer.innerHTML = '<span class="tag">None</span>';
        }
        
        // Populate Tags (Imports)
        const importsContainer = document.getElementById("meta-imports");
        importsContainer.innerHTML = "";
        const imports = data.metadata.dependencies || [];
        if (imports.length > 0) {
            imports.forEach(imp => {
                const tag = document.createElement("span");
                tag.className = "tag";
                tag.textContent = imp;
                importsContainer.appendChild(tag);
            });
        } else {
            importsContainer.innerHTML = '<span class="tag">None</span>';
        }
        
        // Display Code
        const codeDisplay = document.getElementById("code-display");
        const fileExt = filePath.split('.').pop().toLowerCase();
        let prismLang = "none";
        
        if (fileExt === "py") prismLang = "python";
        else if (["js", "jsx", "ts", "tsx"].includes(fileExt)) prismLang = "javascript";
        else if (fileExt === "html") prismLang = "html";
        else if (fileExt === "css") prismLang = "css";
        else if (fileExt === "json") prismLang = "json";
        
        document.getElementById("inspected-lang").textContent = prismLang.toUpperCase();
        
        codeDisplay.className = `language-${prismLang}`;
        codeDisplay.textContent = data.content;
        Prism.highlightElement(codeDisplay);
        
    } catch (error) {
        console.error("Failed loading file details:", error);
    }
}

// MULTI-AGENT PLAYGROUND CHAT
async function sendChatMessage() {
    const inputEl = document.getElementById("chat-input");
    const query = inputEl.value.trim();
    if (!query) return;
    
    // Add user message to history
    appendChatMessage("User", query, "user-message");
    inputEl.value = "";
    
    // Set status to agent working
    updateStatus("Planner Agent working...", "thinking");
    
    // Add typing placeholder for agent
    const typingBubble = appendChatMessage("Agent", "Agent is planning and investigating...", "system-message typing");
    
    try {
        const response = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                query: query,
                api_key: state.apiKey
            })
        });
        
        if (!response.ok) throw new Error("Agent failed to respond.");
        const data = await response.json();
        
        // Remove typing placeholder
        typingBubble.remove();
        
        // Append response
        appendChatMessage("Agent", data.answer, "system-message", data.plan, data.logs);
        
        updateStatus("Standby", "online");
    } catch (error) {
        typingBubble.remove();
        appendChatMessage("Agent", `Error getting response: ${error.message}`, "system-message error");
        updateStatus("Agent Error", "offline");
    }
}

function appendChatMessage(sender, text, cssClass, plan = null, logs = null) {
    const chatContainer = document.getElementById("chat-messages");
    
    const messageEl = document.createElement("div");
    messageEl.className = `message ${cssClass}`;
    
    const avatarEl = document.createElement("div");
    avatarEl.className = "avatar";
    avatarEl.innerHTML = sender === "User" ? '<i data-lucide="user"></i>' : '<i data-lucide="bot"></i>';
    
    const contentEl = document.createElement("div");
    contentEl.className = "message-content";
    
    const bodyEl = document.createElement("div");
    bodyEl.innerHTML = marked.parse(text);
    contentEl.appendChild(bodyEl);
    
    // Append Agent Execution Logs
    if (logs && logs.length > 0) {
        const logsContainer = document.createElement("div");
        logsContainer.className = "agent-logs";
        
        const headerEl = document.createElement("div");
        headerEl.className = "log-header";
        headerEl.innerHTML = '<i data-lucide="chevron-down"></i> Multi-Agent Execution Steps';
        
        const itemsEl = document.createElement("div");
        itemsEl.className = "log-items";
        
        logs.forEach(log => {
            const itemEl = document.createElement("div");
            itemEl.className = `log-item ${log.agent.toLowerCase()}`;
            itemEl.innerHTML = `
                <span class="log-icon-status">✓</span>
                <div>
                    <strong>[${log.agent}] ${log.action}:</strong> ${log.message}
                </div>
            `;
            itemsEl.appendChild(itemEl);
        });
        
        // Fold/Unfold logs logic
        headerEl.addEventListener("click", () => {
            itemsEl.classList.toggle("hidden");
            headerEl.classList.toggle("collapsed");
            const icon = headerEl.querySelector("i");
            icon.setAttribute("data-lucide", itemsEl.classList.contains("hidden") ? "chevron-right" : "chevron-down");
            lucide.createIcons();
        });
        
        logsContainer.appendChild(headerEl);
        logsContainer.appendChild(itemsEl);
        contentEl.appendChild(logsContainer);
    }
    
    messageEl.appendChild(avatarEl);
    messageEl.appendChild(contentEl);
    chatContainer.appendChild(messageEl);
    
    // Scroll chat to bottom
    chatContainer.scrollTop = chatContainer.scrollHeight;
    lucide.createIcons();
    
    return messageEl;
}

// RENDER DEPENDENCY GRAPH (VIS.JS)
async function loadDependencyGraph() {
    const container = document.getElementById("graph-container");
    container.innerHTML = '<div class="loading-text">Generating visual dependency structure...</div>';
    
    try {
        const response = await fetch("/api/graph");
        const graphData = await response.json();
        
        if (graphData.error) {
            container.innerHTML = `<div class="loading-text">Error: ${graphData.error}</div>`;
            return;
        }
        
        if (!graphData.nodes || graphData.nodes.length === 0) {
            container.innerHTML = '<div class="loading-text">Graph is empty. Index some files first.</div>';
            return;
        }
        
        container.innerHTML = ""; // Clear loader
        
        // Custom styling for nodes
        const nodes = graphData.nodes.map(n => {
            const isPy = n.id.endsWith(".py");
            return {
                id: n.id,
                label: n.label,
                title: n.title || n.id,
                shape: "dot",
                size: 20,
                color: {
                    background: isPy ? "#00f2fe" : "#9d4edd",
                    border: "#161c30",
                    highlight: { background: "#4facfe", border: "#00f2fe" }
                },
                font: { color: "#f8fafc", face: "Outfit" }
            };
        });
        
        const edges = graphData.edges.map(e => {
            return {
                from: e.from,
                to: e.to,
                arrows: "to",
                color: { color: "rgba(255, 255, 255, 0.15)", highlight: "#00f2fe" }
            };
        });
        
        const data = { nodes: new vis.DataSet(nodes), edges: new vis.DataSet(edges) };
        
        const options = {
            nodes: { borderWidth: 2 },
            edges: { smooth: { type: "continuous" } },
            physics: {
                barnesHut: { gravitationalConstant: -3000, centralGravity: 0.3, springLength: 95 },
                stabilization: { iterations: 150 }
            }
        };
        
        state.dependencyGraph = new vis.Network(container, data, options);
        
        // Handle double clicking a node -> Open file inspector
        state.dependencyGraph.on("doubleClick", (params) => {
            if (params.nodes.length > 0) {
                const nodeId = params.nodes[0];
                
                // Select tab
                const inspectorTab = document.querySelector('[data-tab="agent-chat"]');
                switchTab("agent-chat", inspectorTab);
                
                // Load file details
                loadFileInspector(nodeId);
            }
        });
        
    } catch (error) {
        container.innerHTML = `<div class="loading-text">Graph Error: ${error.message}</div>`;
    }
}

// DEVELOPER ONBOARDING MODE
async function generateOnboardingRoadmap() {
    const container = document.getElementById("onboarding-content");
    container.innerHTML = '<div class="loading-text">Principal Engineer writing developer roadmap... (takes ~10 seconds)</div>';
    updateStatus("Generating roadmap...", "thinking");
    
    try {
        const response = await fetch(`/api/action/onboarding?api_key=${encodeURIComponent(state.apiKey)}`);
        if (!response.ok) throw new Error("Failed to generate onboarding roadmap.");
        const data = await response.json();
        
        container.innerHTML = marked.parse(data.roadmap);
        updateStatus("Standby", "online");
    } catch (error) {
        container.innerHTML = `<div class="loading-text">Error compiling onboarding tour: ${error.message}</div>`;
        updateStatus("Roadmap Error", "offline");
    }
}

// --- SPECIAL STAFF ENGINEER PRESET MODALS IMPLEMENTATION ---

// 1. Change Impact Analyzer
function openChangeImpactModal() {
    const contentHTML = `
        <div class="modal-impact-grid">
            <div class="form-group">
                <label for="impact-file-select">Filename to modify:</label>
                <input type="text" id="impact-file-select" placeholder="e.g. gitinsight/scanner.py" value="${state.currentFile}">
                <p class="help-text">Select which file you plan to change. The agent will run graph tracing.</p>
            </div>
            <button id="run-impact-btn" class="glow-btn">Analyze Risk</button>
            <div id="impact-results" class="hidden">
                <div class="risk-level-container">
                    Risk Level: <span id="impact-risk-badge" class="risk-badge">Medium</span>
                </div>
                <br>
                <h4>Affected Files:</h4>
                <div class="impact-list" id="impact-list-box"></div>
                <br>
                <h4>Engineering Assessment:</h4>
                <div class="action_reasoning markdown-body" id="impact-reasoning-box"></div>
            </div>
        </div>
    `;
    
    toggleActionModal("Change Impact Analyzer", contentHTML);
    
    // Bind action
    document.getElementById("run-impact-btn").addEventListener("click", runChangeImpactAnalysis);
}

async function runChangeImpactAnalysis() {
    const file = document.getElementById("impact-file-select").value.trim();
    if (!file) return;
    
    const resultsBox = document.getElementById("impact-results");
    const runBtn = document.getElementById("run-impact-btn");
    
    runBtn.textContent = "Analyzing dependencies...";
    runBtn.disabled = true;
    updateStatus("Analyzing risk...", "thinking");
    
    try {
        const response = await fetch("/api/action/change-impact", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                file_path: file,
                api_key: state.apiKey
            })
        });
        
        if (!response.ok) throw new Error("Dependency tracing failed.");
        const data = await response.json();
        
        resultsBox.classList.remove("hidden");
        
        // Set Risk badge
        const badge = document.getElementById("impact-risk-badge");
        badge.className = `risk-badge ${data.risk_level.toLowerCase()}`;
        badge.textContent = data.risk_level;
        
        // Load files
        const list = document.getElementById("impact-list-box");
        list.innerHTML = "";
        if (data.affected_files.length > 0) {
            const ul = document.createElement("ul");
            data.affected_files.forEach(aff => {
                const li = document.createElement("li");
                li.textContent = aff;
                ul.appendChild(li);
            });
            list.appendChild(ul);
        } else {
            list.innerHTML = "<div>None. This file can be modified without breaking local imports.</div>";
        }
        
        // Set Reasoning text
        document.getElementById("impact-reasoning-box").innerHTML = marked.parse(data.reasoning);
        
        updateStatus("Standby", "online");
    } catch (error) {
        alert(error.message);
        updateStatus("Analysis Error", "offline");
    } finally {
        runBtn.textContent = "Analyze Risk";
        runBtn.disabled = false;
    }
}

// 2. Feature Implementation Planner
function openFeaturePlannerModal() {
    const contentHTML = `
        <div class="modal-impact-grid">
            <div class="form-group">
                <label for="feature-desc-input">Feature Description:</label>
                <textarea id="feature-desc-input" placeholder="e.g. Add JWT Token auth mechanism to main.py" rows="4"></textarea>
                <p class="help-text">Explain what you want to build. The agent will design a code addition plan.</p>
            </div>
            <button id="run-planner-btn" class="glow-btn">Generate Plan</button>
            <div id="planner-results" class="hidden plan-block">
                <div class="plan-grid">
                    <div class="plan-section">
                        <h4>Files to Modify</h4>
                        <ul id="plan-modify-list"></ul>
                    </div>
                    <div class="plan-section">
                        <h4>New Files to Create</h4>
                        <ul id="plan-new-list"></ul>
                    </div>
                </div>
                <div>
                    <h4>Implementation Checklists:</h4>
                    <br>
                    <ol class="plan-steps-list" id="plan-steps-box"></ol>
                </div>
                <div>
                    <h4>Architectural approach:</h4>
                    <div class="action_reasoning" id="plan-explanation-box"></div>
                </div>
            </div>
        </div>
    `;
    
    toggleActionModal("Feature Implementation Planner", contentHTML);
    
    document.getElementById("run-planner-btn").addEventListener("click", runFeaturePlanner);
}

async function runFeaturePlanner() {
    const featureText = document.getElementById("feature-desc-input").value.trim();
    if (!featureText) return;
    
    const runBtn = document.getElementById("run-planner-btn");
    const resultsBox = document.getElementById("planner-results");
    
    runBtn.textContent = "Architecting plan...";
    runBtn.disabled = true;
    updateStatus("Planning architecture...", "thinking");
    
    try {
        const response = await fetch("/api/action/feature-plan", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                feature: featureText,
                api_key: state.apiKey
            })
        });
        
        if (!response.ok) throw new Error("Feature planning failed.");
        const data = await response.json();
        
        resultsBox.classList.remove("hidden");
        
        // Populate edit files
        const mod = document.getElementById("plan-modify-list");
        mod.innerHTML = "";
        if (data.files_to_modify.length > 0) {
            data.files_to_modify.forEach(f => {
                const li = document.createElement("li");
                li.textContent = f;
                mod.appendChild(li);
            });
        } else {
            mod.innerHTML = "<li>None</li>";
        }
        
        // Populate new files
        const nw = document.getElementById("plan-new-list");
        nw.innerHTML = "";
        if (data.new_files.length > 0) {
            data.new_files.forEach(f => {
                const li = document.createElement("li");
                li.textContent = f;
                nw.appendChild(li);
            });
        } else {
            nw.innerHTML = "<li>None</li>";
        }
        
        // Populate steps
        const steps = document.getElementById("plan-steps-box");
        steps.innerHTML = "";
        data.steps.forEach((step, idx) => {
            const li = document.createElement("li");
            li.setAttribute("data-step", idx + 1);
            li.textContent = step;
            steps.appendChild(li);
        });
        
        // Populate explanation
        document.getElementById("plan-explanation-box").innerHTML = marked.parse(data.explanation);
        
        updateStatus("Standby", "online");
    } catch (error) {
        alert(error.message);
        updateStatus("Planning Error", "offline");
    } finally {
        runBtn.textContent = "Generate Plan";
        runBtn.disabled = false;
    }
}

// 3. Architecture Evolution Agent
function openArchitectureModal() {
    const contentHTML = `
        <div class="modal-impact-grid">
            <div class="form-group">
                <label for="arch-query-input">Refactoring/Evolution Goal:</label>
                <textarea id="arch-query-input" placeholder="e.g. How can we convert this monolith into microservices? or How can we migrate from Flask to FastAPI?" rows="4"></textarea>
                <p class="help-text">Define your target design boundaries.</p>
            </div>
            <button id="run-arch-btn" class="glow-btn">Deconstruct Monolith</button>
            <div id="arch-results" class="hidden">
                <h4>System Refactoring Design Report:</h4>
                <br>
                <div class="action_reasoning markdown-body" id="arch-report-box"></div>
            </div>
        </div>
    `;
    
    toggleActionModal("Architecture Evolution Decoupler", contentHTML);
    
    document.getElementById("run-arch-btn").addEventListener("click", runArchitectureEvolution);
}

async function runArchitectureEvolution() {
    const query = document.getElementById("arch-query-input").value.trim();
    if (!query) return;
    
    const runBtn = document.getElementById("run-arch-btn");
    const resultsBox = document.getElementById("arch-results");
    
    runBtn.textContent = "Deconstructing structure...";
    runBtn.disabled = true;
    updateStatus("Deconstructing codebase...", "thinking");
    
    try {
        const response = await fetch("/api/action/architecture", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                request: query,
                api_key: state.apiKey
            })
        });
        
        if (!response.ok) throw new Error("Architecture design failed.");
        const data = await response.json();
        
        resultsBox.classList.remove("hidden");
        document.getElementById("arch-report-box").innerHTML = marked.parse(data.report);
        
        updateStatus("Standby", "online");
    } catch (error) {
        alert(error.message);
        updateStatus("Refactoring Error", "offline");
    } finally {
        runBtn.textContent = "Deconstruct Monolith";
        runBtn.disabled = false;
    }
}

// 4. Pull Request review Agent
function openPRReviewModal() {
    const contentHTML = `
        <div class="pr-review-container">
            <div id="diff-input-panel" class="diff-textarea-container">
                <div class="form-group">
                    <label for="pr-diff-input">Paste Git Diff Content:</label>
                    <textarea id="pr-diff-input" placeholder="diff --git a/main.py b/main.py..."></textarea>
                    <p class="help-text">Input changes in standard unified diff format.</p>
                </div>
                <button id="run-pr-review-btn" class="glow-btn">Review Pull Request</button>
            </div>
            
            <div id="pr-review-results" class="hidden">
                <div class="review-grid">
                    <div class="review-panel risks">
                        <h4><i data-lucide="alert-triangle"></i> Runtime Risks</h4>
                        <ul id="pr-risks-box"></ul>
                    </div>
                    <div class="review-panel security">
                        <h4><i data-lucide="shield-alert"></i> Security Concerns</h4>
                        <ul id="pr-security-box"></ul>
                    </div>
                    <div class="review-panel improvements">
                        <h4><i data-lucide="check-circle-2"></i> Improvements</h4>
                        <ul id="pr-improvements-box"></ul>
                    </div>
                </div>
                <br>
                <h4>Review Summary:</h4>
                <br>
                <div class="action_reasoning markdown-body" id="pr-review-text-box"></div>
            </div>
        </div>
    `;
    
    toggleActionModal("PR Code Review Agent", contentHTML);
    
    document.getElementById("run-pr-review-btn").addEventListener("click", runPRReview);
}

async function runPRReview() {
    const diff = document.getElementById("pr-diff-input").value.trim();
    if (!diff) return;
    
    const runBtn = document.getElementById("run-pr-review-btn");
    const resultsBox = document.getElementById("pr-review-results");
    
    runBtn.textContent = "Analyzing code diff...";
    runBtn.disabled = true;
    updateStatus("Reviewing PR changes...", "thinking");
    
    try {
        const response = await fetch("/api/action/pr-review", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                diff: diff,
                api_key: state.apiKey
            })
        });
        
        if (!response.ok) throw new Error("PR review analysis failed.");
        const data = await response.json();
        
        document.getElementById("diff-input-panel").classList.add("hidden");
        resultsBox.classList.remove("hidden");
        
        // Risks
        const rBox = document.getElementById("pr-risks-box");
        rBox.innerHTML = "";
        if (data.risks.length > 0) {
            data.risks.forEach(r => rBox.innerHTML += `<li>${r}</li>`);
        } else {
            rBox.innerHTML = "<li>No critical runtime risks found.</li>";
        }
        
        // Security
        const sBox = document.getElementById("pr-security-box");
        sBox.innerHTML = "";
        if (data.security.length > 0) {
            data.security.forEach(s => sBox.innerHTML += `<li>${s}</li>`);
        } else {
            sBox.innerHTML = "<li>No security vulnerabilities found.</li>";
        }
        
        // Improvements
        const iBox = document.getElementById("pr-improvements-box");
        iBox.innerHTML = "";
        if (data.improvements.length > 0) {
            data.improvements.forEach(imp => iBox.innerHTML += `<li>${imp}</li>`);
        } else {
            iBox.innerHTML = "<li>No code quality improvements needed.</li>";
        }
        
        // Review Text
        document.getElementById("pr-review-text-box").innerHTML = marked.parse(data.review_text);
        
        updateStatus("Standby", "online");
        lucide.createIcons();
    } catch (error) {
        alert(error.message);
        updateStatus("PR Review Error", "offline");
    } finally {
        runBtn.textContent = "Review Pull Request";
        runBtn.disabled = false;
    }
}
