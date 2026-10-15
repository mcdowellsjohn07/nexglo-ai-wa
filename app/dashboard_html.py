"""Modern Single-Page Admin Dashboard for NexgloTV WhatsApp Agent."""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>NexgloTV — AI Agent Staff Dashboard</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #0b0f19;
      --card-bg: #151b2b;
      --border: #232d42;
      --primary: #6366f1;
      --primary-hover: #4f46e5;
      --success: #10b981;
      --warning: #f59e0b;
      --danger: #ef4444;
      --text: #f3f4f6;
      --text-muted: #9ca3af;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Inter', -apple-system, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
      padding: 24px;
      -webkit-font-smoothing: antialiased;
    }
    .header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 24px;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--border);
      flex-wrap: wrap;
      gap: 16px;
    }
    .title-area h1 { font-size: 24px; font-weight: 700; color: #fff; }
    .title-area p { color: var(--text-muted); font-size: 14px; }
    .auth-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .auth-input { width: 220px; }
    input, select, textarea, button {
      font-family: inherit;
      font-size: 14px;
      border-radius: 8px;
      border: 1px solid var(--border);
      background: #1a2236;
      color: #fff;
      padding: 8px 12px;
      outline: none;
      touch-action: manipulation;
    }
    input:focus, select:focus, textarea:focus { border-color: var(--primary); }
    button {
      background: var(--primary);
      border: none;
      cursor: pointer;
      font-weight: 600;
      transition: all 0.2s;
    }
    button:hover { background: var(--primary-hover); }
    button.btn-success { background: var(--success); }
    button.btn-danger { background: var(--danger); }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 20px;
      margin-bottom: 24px;
    }
    .desk-grid {
      grid-template-columns: 360px 1fr;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 20px;
      word-break: break-word;
    }
    .card h2 {
      font-size: 16px;
      font-weight: 600;
      margin-bottom: 16px;
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 10px;
    }
    .stat-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.05); font-size: 14px; gap: 12px; }
    .stat-row:last-child { border-bottom: none; }
    .badge {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 12px;
      font-size: 12px;
      font-weight: 600;
      white-space: nowrap;
    }
    .badge-green { background: rgba(16, 185, 129, 0.2); color: var(--success); }
    .badge-yellow { background: rgba(245, 158, 11, 0.2); color: var(--warning); }
    .badge-blue { background: rgba(99, 102, 241, 0.2); color: #818cf8; }
    .queue-list { max-height: 400px; overflow-y: auto; -webkit-overflow-scrolling: touch; }
    .queue-item {
      padding: 12px;
      border: 1px solid var(--border);
      border-radius: 8px;
      margin-bottom: 10px;
      cursor: pointer;
      background: #141b2d;
      transition: all 0.2s;
    }
    .queue-item:hover, .queue-item.active { border-color: var(--primary); background: #1c263f; }
    .chat-box {
      background: #0f1524;
      border: 1px solid var(--border);
      border-radius: 8px;
      height: 380px;
      overflow-y: auto;
      padding: 12px;
      margin-bottom: 12px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      -webkit-overflow-scrolling: touch;
    }
    .msg { max-width: 82%; padding: 8px 12px; border-radius: 10px; font-size: 13px; line-height: 1.4; word-break: break-word; }
    .msg-user { align-self: flex-start; background: #1f293d; color: #f3f4f6; }
    .msg-bot { align-self: flex-end; background: #3730a3; color: #fff; }
    .msg-staff { align-self: flex-end; background: #059669; color: #fff; }
    .msg-meta { font-size: 10px; opacity: 0.7; margin-top: 4px; }
    .reply-area { display: flex; gap: 8px; }
    .reply-area input { flex: 1; min-width: 0; }
    .chat-header-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

    /* Tablet & Mobile Media Queries */
    @media (max-width: 960px) {
      body { padding: 14px; }
      .header { margin-bottom: 16px; padding-bottom: 12px; }
      .grid { gap: 14px; margin-bottom: 16px; }
      .desk-grid { grid-template-columns: 1fr; }
      .queue-list { max-height: 280px; }
      .chat-box { height: 350px; }
      .btn-mobile-back { display: inline-block !important; }
    }

    @media (max-width: 640px) {
      body { padding: 10px; }
      .title-area h1 { font-size: 19px; }
      .title-area p { font-size: 12px; }
      .auth-bar { width: 100%; display: flex; }
      .auth-input { flex: 1; width: auto; font-size: 16px; }
      .auth-bar button { padding: 8px 14px; }
      .card { padding: 14px; border-radius: 10px; }
      .card h2 { font-size: 15px; flex-direction: column; align-items: stretch; gap: 8px; }
      .chat-header-actions { width: 100%; justify-content: space-between; }
      .chat-header-actions button { flex: 1; text-align: center; font-size: 11px; padding: 8px 6px; }
      .reply-area { flex-direction: column; gap: 6px; }
      .reply-area input { font-size: 16px; padding: 10px 12px; }
      .reply-area button { width: 100%; padding: 12px; font-size: 14px; font-weight: 700; }
      .msg { max-width: 92%; }
      .chat-box { height: 320px; padding: 8px; }
      .queue-list { max-height: 220px; }
      .stat-row { font-size: 13px; }
    }
  </style>
</head>
<body>
  <div class="header">
    <div class="title-area">
      <h1>NexgloTV AI Agent — Staff Console</h1>
      <p>Live WhatsApp Operations, Model Selector & Human Handoff Control</p>
    </div>
    <div class="auth-bar">
      <input type="password" id="adminToken" class="auth-input" placeholder="Enter ADMIN_TOKEN">
      <button onclick="saveToken()">Save Token</button>
    </div>
  </div>

  <div class="grid">
    <!-- Card 1: System Health & Bot Controls -->
    <div class="card">
      <h2>Bot Status & Delivery <span id="healthBadge" class="badge badge-yellow">Checking...</span></h2>
      <div class="stat-row"><span>Business:</span> <strong id="valBusiness">NexgloTV</strong></div>
      <div class="stat-row"><span>WhatsApp Delivery:</span> <span id="valWaMode">-</span></div>
      <div class="stat-row"><span>Auto-Reply Policy:</span> <span id="valAutoMode">-</span></div>
      <div class="stat-row"><span>LLM Provider:</span> <strong id="valProvider">-</strong></div>
      <div class="stat-row"><span>Active Model:</span> <span id="valModel" class="badge badge-blue">-</span></div>
      <div class="stat-row"><span>Signature Enforced:</span> <strong id="valSig">-</strong></div>
      
      <div style="margin-top: 14px; display: flex; flex-direction: column; gap: 8px;">
        <button id="btnToggleDryRun" onclick="toggleDryRun()" style="width: 100%; font-weight: 600;">🛡️ Toggle Dry Run</button>
        <button id="btnToggleAutoMode" onclick="toggleAutoReplyMode()" style="width: 100%; font-weight: 600; background: #374151;">⚙️ Toggle Policy</button>
        <button onclick="fetchHealth(); fetchSettings();" style="width: 100%; font-size: 12px; background: transparent; border: 1px solid var(--border); color: var(--text-muted);">Refresh Status</button>
      </div>
    </div>

    <!-- Card 2: Model Selector -->
    <div class="card">
      <h2>AI Model Selector <span class="badge badge-blue">Zero-Downtime</span></h2>
      <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 12px;">Hot-swap active AI models instantly without restarting your server:</p>
      <div style="margin-bottom: 12px;">
        <label style="font-size: 12px; color: var(--text-muted);">Choose Model:</label>
        <select id="modelSelect" style="width: 100%; margin-top: 4px;">
          <option value="nvidia/nemotron-3.5-lightning:free">NVIDIA Nemotron 3.5 Lightning (100% Free - Default)</option>
          <option value="meta-llama/llama-3.3-70b-instruct">Llama 3.3 70B Instruct (Meta)</option>
          <option value="meta-llama/llama-3.3-70b-instruct:free">Llama 3.3 70B Instruct (Free Tier)</option>
          <option value="google/gemini-2.0-flash-001">Gemini 2.0 Flash (Fastest)</option>
          <option value="deepseek/deepseek-chat">DeepSeek V3 (Reasoning)</option>
          <option value="anthropic/claude-3.5-haiku">Claude 3.5 Haiku (Safety)</option>
          <option value="openai/gpt-4o-mini">GPT-4o Mini (OpenAI)</option>
        </select>
      </div>
      <button onclick="changeModel()" class="btn-success" style="width: 100%;">Apply Model Now</button>
      <p id="modelStatus" style="font-size: 12px; margin-top: 8px; color: var(--success);"></p>
    </div>

    <!-- Card 3: Quick Links -->
    <div class="card">
      <h2>Resources & Documentation</h2>
      <div class="stat-row">
        <span>Swagger API Docs:</span>
        <a href="/docs" target="_blank" style="color: var(--primary); text-decoration: none; font-weight: 600;">Open /docs &rarr;</a>
      </div>
      <div class="stat-row">
        <span>Health Endpoint:</span>
        <a href="/health" target="_blank" style="color: var(--primary); text-decoration: none; font-weight: 600;">Open /health &rarr;</a>
      </div>
      <div class="stat-row">
        <span>Lark Base CRM:</span>
        <a href="https://applink.larksuite.com/client/base" target="_blank" style="color: var(--primary); text-decoration: none; font-weight: 600;">Lark Workspace &rarr;</a>
      </div>
      <div style="margin-top: 18px;">
        <button onclick="runAutomations()" style="width: 100%;">Trigger Automations Run</button>
      </div>
    </div>
  </div>

  <!-- Live Operations & Conversations Desk -->
  <div class="grid desk-grid">
    <div class="card" id="queueListCard">
      <div style="display: flex; gap: 8px; margin-bottom: 12px; border-bottom: 1px solid var(--border); padding-bottom: 10px;">
        <button id="tabAllChats" onclick="switchTab('all')" style="flex: 1; padding: 6px 10px; font-size: 13px; background: var(--primary);">All Chats (<span id="chatsCount">0</span>)</button>
        <button id="tabHandoffs" onclick="switchTab('handoffs')" style="flex: 1; padding: 6px 10px; font-size: 13px; background: #1f293d;">Handoffs (<span id="queueCount">0</span>)</button>
      </div>
      <div id="queueList" class="queue-list">
        <p style="color: var(--text-muted); font-size: 13px; padding: 8px;">Loading chats...</p>
      </div>
      <div style="display: flex; gap: 8px; margin-top: 12px;">
        <button onclick="refreshCurrentTab()" style="flex: 1; font-size: 12px; padding: 6px;">Refresh List</button>
        <span id="pollIndicator" style="font-size: 11px; color: var(--text-muted); align-self: center;">Auto-sync: 4s</span>
      </div>
    </div>

    <div class="card" id="chatCard">
      <h2>
        <span>Chat: <span id="activeContact" style="color: var(--primary);">Select a conversation</span></span>
        <div class="chat-header-actions">
          <button id="btnMobileBackToList" class="btn-mobile-back" onclick="scrollToChatsList()" style="display: none; padding: 6px 12px; font-size: 12px; background: #1f293d; border: 1px solid var(--border); color: #fff;">&larr; Chats</button>
          <button id="contactModeSwitchBtn" onclick="toggleContactMode()" style="display: none; padding: 6px 14px; font-size: 12px; font-weight: 700; border-radius: 20px; transition: all 0.2s; cursor: pointer;"></button>
          <button onclick="refreshActiveChat()" style="padding: 6px 12px; font-size: 12px; background: #374151;">Reload Chat</button>
        </div>
      </h2>
      <div id="chatModeBanner" style="display: none; margin-bottom: 8px; font-size: 12px; padding: 8px 12px; border-radius: 6px;"></div>
      <div id="contactMeta" style="display: none; font-size: 12px; color: var(--text-muted); margin-bottom: 8px; padding: 6px 10px; background: #141b2d; border-radius: 6px;"></div>
      <div id="chatBox" class="chat-box">
        <p style="color: var(--text-muted); font-size: 13px; text-align: center; margin-top: 150px;">Click a conversation from the left to read messages and reply.</p>
      </div>
      <div class="reply-area">
        <input type="text" id="replyText" placeholder="Type a response to send directly to customer on WhatsApp..." onkeydown="if(event.key==='Enter') sendReply()">
        <button onclick="sendReply()">Send to WhatsApp</button>
      </div>
    </div>
  </div>

  <script>
    let currentWaId = null;
    let currentTab = 'all'; // 'all' | 'handoffs'
    let isFetchingChat = false;
    let currentContactHandoff = false;
    let currentDryRun = false;
    let currentAutoMode = 'all';

    function getSavedToken() {
      try {
        return localStorage.getItem("nexglo_admin_token") || "";
      } catch (e) {
        return "";
      }
    }

    function setSavedToken(token) {
      try {
        localStorage.setItem("nexglo_admin_token", token);
      } catch (e) {}
    }

    function getAuthHeader() {
      const el = document.getElementById("adminToken");
      const token = getSavedToken() || (el ? el.value.trim() : "");
      return { "Authorization": "Bearer " + token, "Content-Type": "application/json" };
    }

    function saveToken() {
      const el = document.getElementById("adminToken");
      const token = el ? el.value.trim() : "";
      setSavedToken(token);
      alert("Admin Token saved!");
      fetchHealth();
      fetchSettings();
      refreshCurrentTab();
      fetchModels();
    }

    function initDashboard() {
      const saved = getSavedToken();
      const el = document.getElementById("adminToken");
      if (saved && el) el.value = saved;
      fetchHealth();
      fetchSettings();
      refreshCurrentTab();
      fetchModels();

      // Live auto-polling every 4 seconds
      setInterval(() => {
        refreshCurrentTab(true);
        if (currentWaId) {
          fetchConversation(currentWaId, true);
        }
        fetchSettings();
      }, 4000);
    }

    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", initDashboard);
    } else {
      initDashboard();
    }

    function switchTab(tab) {
      currentTab = tab;
      const btnAll = document.getElementById("tabAllChats");
      const btnHand = document.getElementById("tabHandoffs");
      if (tab === 'all') {
        btnAll.style.background = "var(--primary)";
        btnHand.style.background = "#1f293d";
      } else {
        btnAll.style.background = "#1f293d";
        btnHand.style.background = "var(--primary)";
      }
      refreshCurrentTab();
    }

    function refreshCurrentTab(silent = false) {
      if (currentTab === 'all') {
        fetchAllConversations(silent);
      } else {
        fetchQueue(silent);
      }
    }

    async function fetchHealth() {
      try {
        const res = await fetch("/health");
        const data = await res.json();
        document.getElementById("valBusiness").textContent = data.business || "NexgloTV";
        document.getElementById("valProvider").textContent = data.llm || "-";
        document.getElementById("valSig").textContent = data.signature_verification ? "Yes (Protected)" : "No";
        document.getElementById("healthBadge").textContent = "Operational";
        document.getElementById("healthBadge").className = "badge badge-green";
      } catch (e) {
        document.getElementById("healthBadge").textContent = "Error";
        document.getElementById("healthBadge").className = "badge badge-danger";
      }
    }

    async function fetchSettings() {
      try {
        const res = await fetch("/admin/settings", { headers: getAuthHeader() });
        if (!res.ok) return;
        const data = await res.json();
        const prevAutoMode = currentAutoMode;
        const prevDryRun = currentDryRun;
        currentDryRun = Boolean(data.dry_run);
        currentAutoMode = data.auto_reply_mode || 'all';

        // Update WhatsApp Delivery mode badge & button
        const waModeEl = document.getElementById("valWaMode");
        const dryRunBtn = document.getElementById("btnToggleDryRun");
        if (currentDryRun) {
          waModeEl.innerHTML = '<span class="badge badge-yellow">🛡️ DRY RUN (Muted)</span>';
          dryRunBtn.textContent = "🚀 Switch to LIVE Mode (Enable WhatsApp Replies)";
          dryRunBtn.className = "btn-success";
          dryRunBtn.style.background = "var(--success)";
          dryRunBtn.style.color = "#ffffff";
          dryRunBtn.title = "Dry Run is ACTIVE. All bot outbound messages are muted globally. Click to go LIVE.";
        } else {
          waModeEl.innerHTML = '<span class="badge badge-green">🟢 LIVE (Sending)</span>';
          dryRunBtn.textContent = "🛡️ Activate Dry Run (Mute All Outbox)";
          dryRunBtn.className = "";
          dryRunBtn.style.background = "#d97706";
          dryRunBtn.style.color = "#ffffff";
          dryRunBtn.title = "Bot is LIVE. Click to mute all bot replies globally.";
        }

        // Update Auto-Reply Policy badge & button
        const autoModeEl = document.getElementById("valAutoMode");
        const autoModeBtn = document.getElementById("btnToggleAutoMode");
        if (currentAutoMode === "selective") {
          autoModeEl.innerHTML = '<span class="badge badge-yellow">Selective (Default: Human)</span>';
          autoModeBtn.textContent = "🚀 Switch to Live Mode (Activate All AI Replies)";
          autoModeBtn.style.background = "#2563eb";
          autoModeBtn.style.color = "#ffffff";
          autoModeBtn.title = "Currently in Selective mode (default: Human / bot paused). Click to activate AI replies for all numbers.";
        } else {
          autoModeEl.innerHTML = '<span class="badge badge-green">Live Mode (AI Replies to All)</span>';
          autoModeBtn.textContent = "🎯 Switch to Selective Mode (Default: Human)";
          autoModeBtn.style.background = "#4b5563";
          autoModeBtn.style.color = "#ffffff";
          autoModeBtn.title = "Currently in Live Mode (bot auto-replies to all numbers). Click to switch to Selective mode where default is Human.";
        }

        // If policy or dry run changed from background/another tab, update active chat and list
        if (prevAutoMode && prevAutoMode !== currentAutoMode) {
          refreshCurrentTab(true);
          if (currentWaId) {
            updateChatModeDisplay(currentAutoMode === "selective");
            fetchConversation(currentWaId, true);
          }
        } else if (prevDryRun !== undefined && prevDryRun !== currentDryRun) {
          if (currentWaId) {
            fetchConversation(currentWaId, true);
          }
        }
      } catch (e) {}
    }

    async function toggleDryRun() {
      const targetDryRun = !currentDryRun;
      const confirmMsg = targetDryRun
        ? "Activate Dry Run?\\n\\nThis will immediately MUTE and SILENCE all outgoing WhatsApp replies globally. Outgoing replies will only be logged locally."
        : "Switch to LIVE Delivery?\\n\\nOutgoing messages from the bot and staff will be sent directly to real customer WhatsApp devices!";
      if (!confirm(confirmMsg)) return;

      const btn = document.getElementById("btnToggleDryRun");
      const oldText = btn.textContent;
      btn.textContent = "Updating...";
      btn.disabled = true;
      try {
        const res = await fetch("/admin/settings/dry-run", {
          method: "POST",
          headers: getAuthHeader(),
          body: JSON.stringify({ enabled: targetDryRun })
        });
        if (res.ok) {
          await fetchSettings();
          await fetchHealth();
          if (currentWaId) {
            fetchConversation(currentWaId, true);
          }
        } else {
          const err = await res.json();
          alert("Could not update Dry Run: " + (err.detail ? (err.detail.message || JSON.stringify(err.detail)) : "Error"));
          btn.textContent = oldText;
        }
      } catch (e) {
        alert("Error toggling dry run: " + e);
        btn.textContent = oldText;
      } finally {
        btn.disabled = false;
      }
    }

    async function toggleAutoReplyMode() {
      const targetMode = currentAutoMode === "selective" ? "all" : "selective";
      const confirmMsg = targetMode === "all"
        ? "Switch to Live Mode?\\n\\nThis will activate AI auto-replies for ALL conversations and future incoming messages!"
        : "Switch to Selective Mode?\\n\\nThis will set the default state to Human (bot paused) for all conversations. You can then switch any number to Bot mode individually on this dashboard!";
      if (!confirm(confirmMsg)) return;

      const btn = document.getElementById("btnToggleAutoMode");
      const oldText = btn.textContent;
      btn.textContent = "Updating...";
      btn.disabled = true;
      try {
        const res = await fetch("/admin/settings/auto-reply-mode", {
          method: "POST",
          headers: getAuthHeader(),
          body: JSON.stringify({ mode: targetMode })
        });
        if (res.ok) {
          currentAutoMode = targetMode;
          // Instantly reflect mode in active chat window if open
          if (currentWaId) {
            updateChatModeDisplay(targetMode === "selective");
          }
          await fetchSettings();
          refreshCurrentTab();
          if (currentWaId) {
            fetchConversation(currentWaId, true);
          }
        } else {
          const err = await res.json();
          alert("Could not update Auto-Reply Mode: " + (err.detail ? (err.detail.message || JSON.stringify(err.detail)) : "Error"));
          btn.textContent = oldText;
        }
      } catch (e) {
        alert("Error changing auto-reply mode: " + e);
        btn.textContent = oldText;
      } finally {
        btn.disabled = false;
      }
    }

    async function fetchModels() {
      try {
        const res = await fetch("/admin/models", { headers: getAuthHeader() });
        if (!res.ok) return;
        const data = await res.json();
        document.getElementById("valModel").textContent = data.current_model || "-";
        if (data.recommended && data.recommended.length > 0) {
          const sel = document.getElementById("modelSelect");
          sel.innerHTML = "";
          data.recommended.forEach(m => {
            const opt = document.createElement("option");
            opt.value = m.id;
            opt.textContent = m.name + " (" + m.latency + ")";
            if (m.id === data.current_model) opt.selected = true;
            sel.appendChild(opt);
          });
        }
      } catch (e) {}
    }

    async function changeModel() {
      const model = document.getElementById("modelSelect").value;
      const statusP = document.getElementById("modelStatus");
      statusP.textContent = "Switching model...";
      try {
        const res = await fetch("/admin/models/select", {
          method: "POST",
          headers: getAuthHeader(),
          body: JSON.stringify({ model })
        });
        const data = await res.json();
        if (data.status === "success") {
          statusP.textContent = "Switched to: " + data.current_model;
          document.getElementById("valModel").textContent = data.current_model;
        } else {
          statusP.textContent = "Error switching model";
        }
      } catch (e) {
        statusP.textContent = "Request failed: " + e;
      }
    }

    async function fetchAllConversations(silent = false) {
      try {
        const res = await fetch("/admin/conversations?limit=50", { headers: getAuthHeader() });
        if (!res.ok) return;
        const data = await res.json();
        const convs = data.conversations || [];
        document.getElementById("chatsCount").textContent = convs.length;

        // Also fetch handoff count in background
        fetch("/admin/handoffs", { headers: getAuthHeader() })
          .then(r => r.json())
          .then(d => { if (d.count !== undefined) document.getElementById("queueCount").textContent = d.count; })
          .catch(() => {});

        const list = document.getElementById("queueList");
        if (!convs || convs.length === 0) {
          list.innerHTML = '<p style="color: var(--text-muted); font-size: 13px; padding: 8px;">No conversations yet. When someone messages your WhatsApp, it will appear here!</p>';
          return;
        }
        const prevScroll = list ? list.scrollTop : 0;
        let html = "";
        convs.forEach(c => {
          const isActive = c.wa_id === currentWaId ? " active" : "";
          const name = c.profile_name || c.wa_id;
          const preview = c.last_message ? (c.last_message.length > 55 ? c.last_message.substring(0, 52) + "..." : c.last_message) : (c.state || "active");
          const isHandoff = Boolean(c.handoff);
          const modeBadge = isHandoff 
            ? ' <span class="badge badge-yellow" style="font-size: 10px;">👤 Human</span>' 
            : ' <span class="badge badge-green" style="font-size: 10px;">🤖 Bot</span>';
          html += `<div class="queue-item${isActive}" onclick="selectContact('${c.wa_id}', '${name.replace(/'/g, "\\'")}', ${isHandoff})">
            <div style="display: flex; justify-content: space-between; align-items: baseline;">
              <strong>${name}${modeBadge}</strong>
              <small style="font-size: 10px; color: var(--text-muted);">${c.updated_at ? c.updated_at.split('T')[0] : ''}</small>
            </div>
            <div style="font-size: 12px; color: #9ca3af; margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${preview}</div>
          </div>`;
        });
        list.innerHTML = html;
        if (list) list.scrollTop = prevScroll;
      } catch (e) {}
    }

    async function fetchQueue(silent = false) {
      try {
        const res = await fetch("/admin/handoffs", { headers: getAuthHeader() });
        if (!res.ok) return;
        const data = await res.json();
        const count = data.count || 0;
        document.getElementById("queueCount").textContent = count;
        const list = document.getElementById("queueList");
        if (!data.handoffs || data.handoffs.length === 0) {
          list.innerHTML = '<p style="color: var(--text-muted); font-size: 13px; padding: 8px;">No open customer handoffs.</p>';
          return;
        }
        const prevScroll = list ? list.scrollTop : 0;
        let html = "";
        data.handoffs.forEach(h => {
          const isActive = h.wa_id === currentWaId ? " active" : "";
          const name = h.profile_name || h.wa_id;
          html += `<div class="queue-item${isActive}" onclick="selectContact('${h.wa_id}', '${name.replace(/'/g, "\\'")}', true)">
            <div style="display: flex; justify-content: space-between; align-items: baseline;">
              <strong>${name}</strong> <span class="badge badge-yellow" style="font-size: 10px;">👤 Waiting</span>
            </div>
            <small style='color: #9ca3af;'>Reason: ${h.reason || "Human agent requested"}</small>
          </div>`;
        });
        list.innerHTML = html;
        if (list) list.scrollTop = prevScroll;
      } catch (e) {}
    }

    let latestChatRequestId = 0;

    function selectContact(waId, name, isHandoff = false) {
      currentWaId = waId;
      currentContactHandoff = Boolean(isHandoff);
      document.getElementById("activeContact").textContent = (name || waId) + " (" + waId + ")";
      updateChatModeDisplay(currentContactHandoff);
      fetchConversation(waId, false);
      refreshCurrentTab(true);

      // On mobile/tablet screens, smoothly scroll chat into view so user can view/reply immediately
      if (window.innerWidth < 960) {
        const chatCard = document.getElementById("chatCard");
        if (chatCard) {
          setTimeout(() => chatCard.scrollIntoView({ behavior: 'smooth' }), 50);
        }
      }
    }

    function scrollToChatsList() {
      const el = document.getElementById("queueListCard");
      if (el) el.scrollIntoView({ behavior: 'smooth' });
    }

    function updateChatModeDisplay(isHandoff) {
      currentContactHandoff = Boolean(isHandoff);
      const btn = document.getElementById("contactModeSwitchBtn");
      const banner = document.getElementById("chatModeBanner");
      const input = document.getElementById("replyText");

      if (!currentWaId) {
        if (btn) btn.style.display = "none";
        if (banner) banner.style.display = "none";
        return;
      }

      if (btn) {
        btn.style.display = "inline-block";
        btn.disabled = false;
        if (currentContactHandoff) {
          btn.innerHTML = "👤 Human Staff (Bot Paused) &bull; <strong>Click to Switch to 🤖 Bot</strong>";
          btn.style.background = "#059669";
          btn.style.color = "#ffffff";
          btn.style.border = "1px solid #10b981";
          btn.title = "Currently in Human Staff mode (Bot paused). Click to activate AI Bot replies for this contact.";
        } else {
          btn.innerHTML = "🤖 AI Bot Active &bull; <strong>Click to Switch to 👤 Human</strong>";
          btn.style.background = "#d97706";
          btn.style.color = "#ffffff";
          btn.style.border = "1px solid #f59e0b";
          btn.title = "Currently in AI Bot mode. Click to take over as Human staff and pause the bot.";
        }
      }

      if (banner) {
        banner.style.display = "block";
        if (currentContactHandoff) {
          banner.style.background = "rgba(245, 158, 11, 0.12)";
          banner.style.border = "1px solid rgba(245, 158, 11, 0.35)";
          banner.style.color = "#fef3c7";
          banner.innerHTML = "👤 <strong>Human Staff Mode:</strong> AI auto-replies are paused for this customer. Type a message below to respond directly, or click the button above to switch to 🤖 Bot.";
        } else {
          banner.style.background = "rgba(16, 185, 129, 0.12)";
          banner.style.border = "1px solid rgba(16, 185, 129, 0.35)";
          banner.style.color = "#d1fae5";
          banner.innerHTML = "🤖 <strong>AI Bot Active:</strong> NexgloTV AI is actively responding to customer messages. Click the button above to switch to 👤 Human.";
        }
      }

      if (input) {
        if (currentContactHandoff) {
          input.placeholder = "Type a response to send directly to customer on WhatsApp...";
        } else {
          input.placeholder = "Staff message (sending will also take over and switch to Human mode)...";
        }
      }

      updateMetaBadge(currentContactHandoff);
    }

    function updateContactModeButton(isHandoff) {
      updateChatModeDisplay(isHandoff);
    }

    function updateMetaBadge(isHandoff) {
      const badgeEl = document.getElementById("contactStatusBadge");
      if (badgeEl) {
        if (isHandoff) {
          badgeEl.className = "badge badge-yellow";
          badgeEl.innerHTML = "👤 HUMAN AGENT (Bot Paused)";
        } else {
          badgeEl.className = "badge badge-green";
          badgeEl.innerHTML = "🤖 AI BOT ACTIVE";
        }
      }
    }

    function renderContactMeta(data) {
      const metaDiv = document.getElementById("contactMeta");
      if (!metaDiv) return;
      const isHandoff = Boolean(data.handoff);
      const statusBadge = isHandoff 
        ? '<span id="contactStatusBadge" class="badge badge-yellow" style="margin-left: 6px;">👤 HUMAN AGENT (Bot Paused)</span>' 
        : '<span id="contactStatusBadge" class="badge badge-green" style="margin-left: 6px;">🤖 AI BOT ACTIVE</span>';
      
      let metaHtml = `<strong>Status:</strong> ${escapeHtml(data.state || 'active')} ${statusBadge} | <strong>Lang:</strong> ${(data.lang || 'en').toUpperCase()}`;
      
      if (currentDryRun) {
        metaHtml += ` | <span class="badge badge-yellow" style="font-size: 10px;">🛡️ DRY RUN (Replies Muted)</span>`;
      }
      if (currentAutoMode === "selective") {
        metaHtml += ` | <span style="color: #93c5fd; font-size: 11px;">Policy: Selective</span>`;
      } else {
        metaHtml += ` | <span style="color: #86efac; font-size: 11px;">Policy: Live</span>`;
      }
      if (data.draft && data.draft.quote) {
        metaHtml += ` | <strong>Draft Quote:</strong> Le ${Number(data.draft.quote).toLocaleString()}`;
      }
      if (data.lead && data.lead.stage) {
        metaHtml += ` | <strong>Lead Stage:</strong> ${escapeHtml(data.lead.stage)}`;
      }
      metaDiv.innerHTML = metaHtml;
      metaDiv.style.display = "block";
    }

    async function toggleContactMode() {
      if (!currentWaId) return;
      const targetMode = currentContactHandoff ? "bot" : "human";
      const btn = document.getElementById("contactModeSwitchBtn");
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = "⏳ Switching mode...";
      }

      try {
        const res = await fetch("/admin/conversations/" + currentWaId + "/mode", {
          method: "POST",
          headers: getAuthHeader(),
          body: JSON.stringify({ mode: targetMode })
        });
        if (res.ok) {
          const newHandoff = (targetMode === "human");
          updateChatModeDisplay(newHandoff);
          await fetchConversation(currentWaId, true);
          refreshCurrentTab(true);
        } else {
          const err = await res.json();
          alert("Could not switch mode: " + (err.detail ? (err.detail.message || JSON.stringify(err.detail)) : "Error"));
          updateChatModeDisplay(currentContactHandoff);
        }
      } catch (e) {
        alert("Error switching mode: " + e);
        updateChatModeDisplay(currentContactHandoff);
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    function refreshActiveChat() {
      if (currentWaId) {
        fetchConversation(currentWaId, false);
      }
    }

    async function fetchConversation(waId, silent = false) {
      if (!waId) return;
      const thisRequestId = ++latestChatRequestId;
      const chatBox = document.getElementById("chatBox");
      if (!silent && chatBox) {
        chatBox.innerHTML = "<p style='color: var(--text-muted); font-size: 13px; text-align: center; margin-top: 150px;'>Loading conversation transcript...</p>";
      }
      try {
        const res = await fetch("/admin/conversations/" + waId, { headers: getAuthHeader() });
        if (thisRequestId !== latestChatRequestId || waId !== currentWaId) {
          return;
        }
        if (!res.ok) return;
        const data = await res.json();
        if (thisRequestId !== latestChatRequestId || waId !== currentWaId) {
          return;
        }

        currentContactHandoff = Boolean(data.handoff);
        updateChatModeDisplay(currentContactHandoff);
        renderContactMeta(data);

        const msgs = data.messages || data.transcript || [];
        if (msgs.length === 0) {
          chatBox.innerHTML = "<p style='color: var(--text-muted); font-size: 13px; text-align: center; margin-top: 150px;'>No messages recorded for this contact yet.</p>";
          return;
        }

        let html = "";
        msgs.forEach(m => {
          const author = m.author || "bot";
          const time = m.created_at ? (m.created_at.includes("T") ? m.created_at.replace("T", " ").split(".")[0] : m.created_at) : "";
          html += `<div class="msg msg-${author}">
            <div>${escapeHtml(m.content || m.body || m.text || "")}</div>
            <div class="msg-meta">${author.toUpperCase()} &bull; ${time}</div>
          </div>`;
        });

        const isAtBottom = (chatBox.scrollHeight - chatBox.scrollTop - chatBox.clientHeight) < 60;
        chatBox.innerHTML = html;
        if (!silent || isAtBottom) {
          chatBox.scrollTop = chatBox.scrollHeight;
        }
      } catch (e) {
        console.error("fetchConversation error:", e);
      }
    }

    function escapeHtml(text) {
      const div = document.createElement('div');
      div.textContent = text;
      return div.innerHTML;
    }

    async function sendReply() {
      if (!currentWaId) return alert("Please select a conversation from the list first!");
      const input = document.getElementById("replyText");
      const text = input.value.trim();
      if (!text) return;
      try {
        const res = await fetch("/admin/conversations/" + currentWaId + "/reply", {
          method: "POST",
          headers: getAuthHeader(),
          body: JSON.stringify({ text })
        });
        if (res.ok) {
          input.value = "";
          updateChatModeDisplay(true);
          fetchConversation(currentWaId, false);
          refreshCurrentTab(true);
        } else {
          const err = await res.json();
          alert("Could not send reply: " + (err.detail ? (err.detail.message || JSON.stringify(err.detail)) : "Error"));
        }
      } catch (e) {
        alert("Failed to send: " + e);
      }
    }

    async function takeoverChat() {
      if (!currentWaId) return;
      currentContactHandoff = false;
      await toggleContactMode();
    }

    async function resolveChat() {
      if (!currentWaId) return;
      currentContactHandoff = true;
      await toggleContactMode();
    }

    async function runAutomations() {
      try {
        const res = await fetch("/admin/automations/run", {
          method: "POST",
          headers: getAuthHeader(),
          body: JSON.stringify({})
        });
        const data = await res.json();
        alert("Automations completed! Processed: " + JSON.stringify(data));
      } catch (e) {
        alert("Failed to run automations: " + e);
      }
    }
  </script>
</body>
</html>
"""
