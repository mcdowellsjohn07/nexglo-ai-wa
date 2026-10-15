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
    .auth-bar { display: flex; align-items: center; gap: 8px; }
    input, select, textarea, button {
      font-family: inherit;
      font-size: 14px;
      border-radius: 8px;
      border: 1px solid var(--border);
      background: #1a2236;
      color: #fff;
      padding: 8px 12px;
      outline: none;
    }
    input:focus, select:focus, textarea:focus { border-color: var(--primary); }
    button {
      background: var(--primary);
      border: none;
      cursor: pointer;
      font-weight: 600;
      transition: background 0.2s;
    }
    button:hover { background: var(--primary-hover); }
    button.btn-success { background: var(--success); }
    button.btn-danger { background: var(--danger); }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 20px;
      margin-bottom: 24px;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 20px;
    }
    .card h2 { font-size: 16px; font-weight: 600; margin-bottom: 16px; color: #fff; display: flex; align-items: center; justify-content: space-between; }
    .stat-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.05); font-size: 14px; }
    .stat-row:last-child { border-bottom: none; }
    .badge {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 12px;
      font-size: 12px;
      font-weight: 600;
    }
    .badge-green { background: rgba(16, 185, 129, 0.2); color: var(--success); }
    .badge-yellow { background: rgba(245, 158, 11, 0.2); color: var(--warning); }
    .badge-blue { background: rgba(99, 102, 241, 0.2); color: #818cf8; }
    .queue-list { max-height: 280px; overflow-y: auto; }
    .queue-item {
      padding: 12px;
      border: 1px solid var(--border);
      border-radius: 8px;
      margin-bottom: 10px;
      cursor: pointer;
      background: #141b2d;
      transition: border-color 0.2s;
    }
    .queue-item:hover, .queue-item.active { border-color: var(--primary); background: #1c263f; }
    .chat-box {
      background: #0f1524;
      border: 1px solid var(--border);
      border-radius: 8px;
      height: 280px;
      overflow-y: auto;
      padding: 12px;
      margin-bottom: 12px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .msg { max-width: 80%; padding: 8px 12px; border-radius: 10px; font-size: 13px; line-height: 1.4; }
    .msg-user { align-self: flex-start; background: #1f293d; color: #f3f4f6; }
    .msg-bot { align-self: flex-end; background: #3730a3; color: #fff; }
    .msg-staff { align-self: flex-end; background: #059669; color: #fff; }
    .msg-meta { font-size: 10px; opacity: 0.7; margin-top: 4px; }
    .reply-area { display: flex; gap: 8px; }
    .reply-area input { flex: 1; }
  </style>
</head>
<body>
  <div class="header">
    <div class="title-area">
      <h1>NexgloTV AI Agent — Staff Console</h1>
      <p>Live WhatsApp Operations, Model Selector & Human Handoff Control</p>
    </div>
    <div class="auth-bar">
      <input type="password" id="adminToken" placeholder="Enter ADMIN_TOKEN" style="width: 220px;">
      <button onclick="saveToken()">Save Token</button>
    </div>
  </div>

  <div class="grid">
    <!-- Card 1: System Health -->
    <div class="card">
      <h2>Bot Status <span id="healthBadge" class="badge badge-yellow">Checking...</span></h2>
      <div class="stat-row"><span>Business:</span> <strong id="valBusiness">NexgloTV</strong></div>
      <div class="stat-row"><span>WhatsApp Mode:</span> <strong id="valWaMode">-</strong></div>
      <div class="stat-row"><span>LLM Provider:</span> <strong id="valProvider">-</strong></div>
      <div class="stat-row"><span>Active Model:</span> <span id="valModel" class="badge badge-blue">-</span></div>
      <div class="stat-row"><span>Signature Enforced:</span> <strong id="valSig">-</strong></div>
      <div style="margin-top: 14px;">
        <button onclick="fetchHealth()" style="width: 100%;">Refresh Status</button>
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
  <div class="grid" style="grid-template-columns: 360px 1fr;">
    <div class="card">
      <div style="display: flex; gap: 8px; margin-bottom: 12px; border-bottom: 1px solid var(--border); padding-bottom: 10px;">
        <button id="tabAllChats" onclick="switchTab('all')" style="flex: 1; padding: 6px 10px; font-size: 13px; background: var(--primary);">All Chats (<span id="chatsCount">0</span>)</button>
        <button id="tabHandoffs" onclick="switchTab('handoffs')" style="flex: 1; padding: 6px 10px; font-size: 13px; background: #1f293d;">Handoffs (<span id="queueCount">0</span>)</button>
      </div>
      <div id="queueList" class="queue-list" style="max-height: 400px;">
        <p style="color: var(--text-muted); font-size: 13px; padding: 8px;">Loading chats...</p>
      </div>
      <div style="display: flex; gap: 8px; margin-top: 12px;">
        <button onclick="refreshCurrentTab()" style="flex: 1; font-size: 12px; padding: 6px;">Refresh List</button>
        <span id="pollIndicator" style="font-size: 11px; color: var(--text-muted); align-self: center;">Auto-sync: 4s</span>
      </div>
    </div>

    <div class="card">
      <h2>
        <span>Chat: <span id="activeContact" style="color: var(--primary);">Select a conversation</span></span>
        <div>
          <button id="resolveBtn" onclick="resolveChat()" class="btn-success" style="display: none; padding: 4px 10px; font-size: 12px; margin-right: 8px;">Resolve Handoff</button>
          <button onclick="refreshActiveChat()" style="padding: 4px 10px; font-size: 12px; background: #374151;">Reload Chat</button>
        </div>
      </h2>
      <div id="contactMeta" style="display: none; font-size: 12px; color: var(--text-muted); margin-bottom: 8px; padding: 6px 10px; background: #141b2d; border-radius: 6px;"></div>
      <div id="chatBox" class="chat-box" style="height: 380px;">
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

    function getAuthHeader() {
      const token = localStorage.getItem("nexglo_admin_token") || document.getElementById("adminToken").value.trim();
      return { "Authorization": "Bearer " + token, "Content-Type": "application/json" };
    }

    function saveToken() {
      const token = document.getElementById("adminToken").value.trim();
      localStorage.setItem("nexglo_admin_token", token);
      alert("Admin Token saved!");
      fetchHealth();
      refreshCurrentTab();
      fetchModels();
    }

    window.onload = function() {
      const saved = localStorage.getItem("nexglo_admin_token");
      if (saved) document.getElementById("adminToken").value = saved;
      fetchHealth();
      refreshCurrentTab();
      fetchModels();

      // Live auto-polling every 4 seconds
      setInterval(() => {
        refreshCurrentTab(true);
        if (currentWaId) {
          fetchConversation(currentWaId, true);
        }
      }, 4000);
    };

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
        document.getElementById("valWaMode").textContent = data.dry_run ? "Dry Run (Offline)" : "LIVE (Connected to Meta)";
        document.getElementById("valProvider").textContent = data.llm || "-";
        document.getElementById("valSig").textContent = data.signature_verification ? "Yes (Protected)" : "No";
        document.getElementById("healthBadge").textContent = "Operational";
        document.getElementById("healthBadge").className = "badge badge-green";
      } catch (e) {
        document.getElementById("healthBadge").textContent = "Error";
        document.getElementById("healthBadge").className = "badge badge-danger";
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
        let html = "";
        convs.forEach(c => {
          const isActive = c.wa_id === currentWaId ? " active" : "";
          const name = c.profile_name || c.wa_id;
          const preview = c.last_message ? (c.last_message.length > 55 ? c.last_message.substring(0, 52) + "..." : c.last_message) : (c.state || "active");
          const handoffBadge = c.handoff ? ' <span class="badge badge-yellow" style="font-size: 10px;">Handoff</span>' : '';
          html += `<div class="queue-item${isActive}" onclick="selectContact('${c.wa_id}', '${name.replace(/'/g, "\\'")}', ${c.handoff})">
            <div style="display: flex; justify-content: space-between; align-items: baseline;">
              <strong>${name}${handoffBadge}</strong>
              <small style="font-size: 10px; color: var(--text-muted);">${c.updated_at ? c.updated_at.split('T')[0] : ''}</small>
            </div>
            <div style="font-size: 12px; color: #9ca3af; margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${preview}</div>
          </div>`;
        });
        list.innerHTML = html;
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
        let html = "";
        data.handoffs.forEach(h => {
          const isActive = h.wa_id === currentWaId ? " active" : "";
          const name = h.profile_name || h.wa_id;
          html += `<div class="queue-item${isActive}" onclick="selectContact('${h.wa_id}', '${name.replace(/'/g, "\\'")}', true)">
            <strong>${name}</strong> <span class="badge badge-yellow" style="font-size: 10px;">Waiting</span><br>
            <small style='color: #9ca3af;'>Reason: ${h.reason || "Human agent requested"}</small>
          </div>`;
        });
        list.innerHTML = html;
      } catch (e) {}
    }

    function selectContact(waId, name, isHandoff = false) {
      currentWaId = waId;
      document.getElementById("activeContact").textContent = (name || waId) + " (" + waId + ")";
      const resolveBtn = document.getElementById("resolveBtn");
      resolveBtn.style.display = isHandoff ? "inline-block" : "none";
      fetchConversation(waId, false);
      refreshCurrentTab(true);
    }

    function refreshActiveChat() {
      if (currentWaId) {
        fetchConversation(currentWaId, false);
      }
    }

    async function fetchConversation(waId, silent = false) {
      if (isFetchingChat) return;
      isFetchingChat = true;
      const chatBox = document.getElementById("chatBox");
      if (!silent) {
        chatBox.innerHTML = "<p style='color: var(--text-muted); font-size: 13px; text-align: center; margin-top: 150px;'>Loading conversation transcript...</p>";
      }
      try {
        const res = await fetch("/admin/conversations/" + waId, { headers: getAuthHeader() });
        if (!res.ok) { isFetchingChat = false; return; }
        const data = await res.json();
        const msgs = data.messages || data.transcript || [];

        // Meta info strip
        const metaDiv = document.getElementById("contactMeta");
        let metaHtml = `<strong>Status:</strong> ${data.state || 'active'} | <strong>Lang:</strong> ${(data.lang || 'en').toUpperCase()}`;
        if (data.draft && data.draft.quote) {
          metaHtml += ` | <strong>Draft Quote:</strong> Le ${data.draft.quote.toLocaleString()}`;
        }
        if (data.lead && data.lead.stage) {
          metaHtml += ` | <strong>Lead Stage:</strong> ${data.lead.stage}`;
        }
        metaDiv.innerHTML = metaHtml;
        metaDiv.style.display = "block";

        if (data.handoff) {
          document.getElementById("resolveBtn").style.display = "inline-block";
        }

        if (msgs.length === 0) {
          chatBox.innerHTML = "<p style='color: var(--text-muted); font-size: 13px; text-align: center; margin-top: 150px;'>No messages recorded for this contact yet.</p>";
          isFetchingChat = false;
          return;
        }

        // Render messages
        let html = "";
        msgs.forEach(m => {
          const author = m.author || "bot";
          const time = m.created_at ? (m.created_at.includes("T") ? m.created_at.replace("T", " ").split(".")[0] : m.created_at) : "";
          html += `<div class="msg msg-${author}">
            <div>${escapeHtml(m.content || m.body || m.text || "")}</div>
            <div class="msg-meta">${author.toUpperCase()} &bull; ${time}</div>
          </div>`;
        });

        // Check if user was already at bottom to keep scrolled
        const isAtBottom = (chatBox.scrollHeight - chatBox.scrollTop - chatBox.clientHeight) < 60;
        chatBox.innerHTML = html;
        if (!silent || isAtBottom) {
          chatBox.scrollTop = chatBox.scrollHeight;
        }
      } catch (e) {
      } finally {
        isFetchingChat = false;
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
          fetchConversation(currentWaId, false);
        } else {
          const err = await res.json();
          alert("Could not send reply: " + (err.detail ? (err.detail.message || JSON.stringify(err.detail)) : "Error"));
        }
      } catch (e) {
        alert("Failed to send: " + e);
      }
    }

    async function resolveChat() {
      if (!currentWaId) return;
      try {
        await fetch("/admin/handoffs/" + currentWaId + "/resolve", {
          method: "POST",
          headers: getAuthHeader(),
          body: JSON.stringify({ notify: true })
        });
        alert("Conversation resolved! Handed back to the AI bot.");
        document.getElementById("resolveBtn").style.display = "none";
        refreshCurrentTab();
        fetchConversation(currentWaId, false);
      } catch (e) {
        alert("Error: " + e);
      }
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
