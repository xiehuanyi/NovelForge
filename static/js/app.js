const state = {
  agents: [],
  agentMap: {},
  chat: [],
  settings: null,
  chapters: [],
  showBackstage: false,
  activeChapter: null,
  mentionStart: null,
};

const views = {
  create: document.getElementById("view-create"),
  reviews: document.getElementById("view-reviews"),
  projects: document.getElementById("view-projects"),
};

const chatLog = document.getElementById("chat-log");
const chatInput = document.getElementById("chat-input");
const sendBtn = document.getElementById("send-btn");
const sidebarMeta = document.getElementById("sidebar-meta");
const mentionMenu = document.getElementById("mention-menu");

const chapterList = document.getElementById("chapter-list");
const readerTitle = document.getElementById("reader-title");
const readerContent = document.getElementById("reader-content");
const readerEditor = document.getElementById("reader-editor");
const editChapterBtn = document.getElementById("edit-chapter-btn");
const saveChapterBtn = document.getElementById("save-chapter-btn");

const projectDashboard = document.getElementById("project-dashboard");
const projectSelectorDisplay = document.getElementById("project-selector-display");
// Removed legacy project selector elements

const navButtons = document.querySelectorAll(".nav-btn");

// ... (palette code remains) ...

// Project Management Logic
async function refreshProjects() {
  try {
    const projects = await fetchJSON("/api/projects");
    projectDashboard.innerHTML = "";

    // 1. Render "Create New" Card
    const createCard = document.createElement("div");
    createCard.className = "project-card new-project-card";
    createCard.innerHTML = `<div class="icon">+</div><div>Create New Series</div>`;
    createCard.onclick = handleCreateProject;
    projectDashboard.appendChild(createCard);

    // 2. Render Project Cards
    projects.forEach(p => {
      const card = document.createElement("div");
      card.className = "project-card";
      // Format date
      const dateStr = p.updated_at
        ? new Date(p.updated_at * 1000).toLocaleDateString() + " " + new Date(p.updated_at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        : "Unknown";

      card.innerHTML = `
        <div class="card-title">${p.title || p.slug}</div>
        <div class="card-meta">
           Last Active: ${dateStr}
        </div>
      `;
      card.onclick = () => handleProjectSwitch(p.slug);
      projectDashboard.appendChild(card);
    });

  } catch (e) {
    console.error("Failed to list projects", e);
    projectDashboard.innerHTML = `<div style="color:red">Failed to load projects: ${e.message}</div>`;
  }
}

async function handleCreateProject() {
  // Optional: Prompt for title, but default allow empty
  // const title = prompt("Enter Project Title (optional):");
  // if (title === null) return; // Cancelled

  // Changing UX: Just create immediately with "Untitled", user can rename later (future feature)
  // Or maybe we can't properly prompt in a card click? 
  // Let's use a simple prompt for now to give some control, or just empty.
  // User requirement: "not necessarily give a title immediately".

  // Let's just create directly.
  try {
    const res = await fetchJSON("/api/projects/new", {
      method: "POST",
      body: JSON.stringify({ title: "" })
    });
    await handleProjectSwitch(res.slug);
  } catch (e) {
    alert("Create Failed: " + e.message);
  }
}


const palette = [
  "linear-gradient(150deg, #f4d35e, #e07a5f)",
  "linear-gradient(160deg, #84a59d, #f6bd60)",
  "linear-gradient(150deg, #a8dadc, #457b9d)",
  "linear-gradient(140deg, #f7b267, #f79d65)",
  "linear-gradient(160deg, #e9c46a, #2a9d8f)",
];

function fetchJSON(url, options = {}) {
  return fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  }).then((res) => {
    if (!res.ok) {
      return res.json().then((data) => {
        throw new Error(data.detail || "Request Failed");
      });
    }
    return res.json();
  });
}

function switchView(name) {
  Object.values(views).forEach((view) => view.classList.remove("active"));
  views[name].classList.add("active");
  navButtons.forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === name);
  });
}

function renderAgents() {
  // Roster removed by user request
}

function renderChat() {
  chatLog.innerHTML = "";
  const ordered = [...state.chat].sort((a, b) => a.timestamp - b.timestamp);
  ordered.forEach((msg) => {
    const agent = state.agentMap[msg.agent_id] || { name: "System", color: "#888" };
    const isUser = msg.role === "user";
    const displayName = isUser ? "You" : agent.name;
    const avatarColor = isUser ? "var(--accent-2)" : agent.color;
    const wrapper = document.createElement("div");
    wrapper.className = `message ${isUser ? "user" : "agent"}`;
    wrapper.innerHTML = `
      <div class="avatar" style="background: ${avatarColor}">${displayName.slice(0, 1)}</div>
      <div class="message-body">
        <div class="message-header">
          <strong>${displayName}</strong>
          <span>${new Date(msg.timestamp * 1000).toLocaleTimeString()}</span>
        </div>
        <div class="message-content"></div>
      </div>
    `;
    if (msg.pending) {
      wrapper.querySelector(".message-content").innerHTML = `
        <span class="typing"><span></span><span></span><span></span></span>
      `;
    } else {
      wrapper.querySelector(".message-content").textContent = msg.content;
    }

    // Retry Button Injection
    if (msg.hasRetry) {
      const btnDiv = document.createElement("div");
      btnDiv.style.marginTop = "10px";

      const btn = document.createElement("button");
      btn.className = "action-btn";

      if (msg.retryAction === "auto_gen") {
        btn.onclick = function () { retryAutoGen(this); };
        btn.innerHTML = "🔄 Retry Generation";
      } else {
        btn.onclick = function () { retryLastMessage(this); };
        btn.innerHTML = "🔄 Retry Previous Request";
      }

      btnDiv.appendChild(btn);
      wrapper.querySelector(".message-content").appendChild(btnDiv);
    }

    // Setup Form Injection
    if (msg.setup_data && !msg.setup_confirmed) {
      const data = msg.setup_data;
      const setupHtml = `
        <div class="setup-form" style="margin-top: 15px; padding-top: 15px; border-top: 1px solid var(--line);">
          <div class="settings-group" style="margin-bottom: 10px;">
            <label>书名 Title</label>
            <input type="text" class="setup-title" value="${data.title || ''}" placeholder="Untitled">
          </div>
          <div class="settings-group" style="margin-bottom: 10px;">
            <label>核心创意 Idea</label>
            <textarea class="setup-idea" rows="3">${data.idea || ''}</textarea>
          </div>
           <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 10px;">
            <div class="settings-group">
                <label>题材 Genre</label>
                <input type="text" class="setup-genre" value="${data.genre || ''}" placeholder="e.g. Sci-Fi">
            </div>
            <div class="settings-group">
                <label>风格 Style</label>
                <input type="text" class="setup-style" value="${data.style || ''}" placeholder="e.g. Dark">
            </div>
          </div>
           <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 10px;">
            <div class="settings-group">
                <label>Chapters</label>
                <input type="number" class="setup-chapters" value="${data.chapters || 10}">
            </div>
            <div class="settings-group">
                <label>Words/CH</label>
                <input type="number" class="setup-words" value="${data.chapter_words || 2000}">
            </div>
          </div>
          <div class="settings-actions">
            <button class="confirm-setup-btn" data-msg-id="${msg.id}" style="width: 100%; border-radius: 8px;">Confirm & Start</button>
          </div>
        </div>
      `;
      wrapper.querySelector(".message-body").insertAdjacentHTML('beforeend', setupHtml);
    } else if (msg.setup_confirmed) {
      wrapper.querySelector(".message-body").insertAdjacentHTML('beforeend',
        `<div style="margin-top:10px; color:var(--accent-2); font-size:13px;">✅ Settings Confirmed</div>`
      );
    }

    chatLog.appendChild(wrapper);
  });
  chatLog.scrollTop = chatLog.scrollHeight;
  bindActionButtons();
}

// Handler for Setup Form
function handleSetupConfirm(btn) {
  const msgId = btn.dataset.msgId;
  const msg = state.chat.find(m => m.id === msgId);
  if (!msg) return;

  const container = btn.closest(".setup-form");
  const title = container.querySelector(".setup-title").value;
  const idea = container.querySelector(".setup-idea").value;
  const genre = container.querySelector(".setup-genre").value;
  const style = container.querySelector(".setup-style").value;
  const chapters = parseInt(container.querySelector(".setup-chapters").value);
  const words = parseInt(container.querySelector(".setup-words").value);

  // 1. Save Settings
  fetchJSON("/api/settings", {
    method: "POST",
    body: JSON.stringify({
      title,
      idea,
      chapters,
      chapter_words: words
    })
  }).then(() => {
    // 2. Mark locally as confirmed to hide form
    msg.setup_confirmed = true;
    renderChat();

    // 3. Trigger Architect with the full context
    let prompt = `@Architect Please start designing the series bible.`;
    prompt += `\nIdea: ${idea}`;
    if (genre) prompt += `\nGenre: ${genre}`;
    if (style) prompt += `\nStyle: ${style}`;

    chatInput.value = prompt;
    sendChat();
  });
}


function renderProjectMeta() {
  if (!state.settings) {
    sidebarMeta.textContent = "Total Tokens: 0";
    return;
  }
  const spec = state.settings.spec;
  // Use backend provided total_tokens if available, or 0
  const totalTokens = state.settings.total_tokens || 0;
  sidebarMeta.textContent = `Total Generated Tokens: ${totalTokens.toLocaleString()}`;

  if (projectSelectorDisplay) {
    // Show Title if available, else Slug
    projectSelectorDisplay.value = spec.title || state.settings.project_slug || "No Project Loaded";
  }
}



function renderChapters() {
  chapterList.innerHTML = "";
  if (!state.chapters.length) {
    chapterList.innerHTML = "<p>暂无章节，先去 Create 生成。</p>";
    return;
  }
  state.chapters.forEach((chapter, index) => {
    const card = document.createElement("div");
    card.className = "book-card";
    card.style.background = palette[index % palette.length];
    card.innerHTML = `
      <span class="book-status">${chapter.status || "draft"}</span>
      <div>
        <h4>CH${String(chapter.chapter).padStart(3, "0")}</h4>
        <span>${chapter.title || "Untitled"}</span>
      </div>
    `;
    card.addEventListener("click", () => loadChapter(`CH${String(chapter.chapter).padStart(4, "0")}`));
    chapterList.appendChild(card);
  });
}

let isEditing = false; // Add this line before loadChapter function

async function loadChapter(chapterId) {
  try {
    const data = await fetchJSON(`/api/preview/chapter/${chapterId}`);
    state.activeChapter = chapterId;
    const content = data.content || "";

    // Reset view
    isEditing = false;
    readerContent.style.display = "block";
    readerEditor.style.display = "none";
    editChapterBtn.style.display = "inline-block";
    saveChapterBtn.style.display = "none";

    readerTitle.textContent = `${chapterId} · ${data.title || ""}  [${content.length} chars]`;
    readerContent.textContent = content;

    // Bind Edit Button
    editChapterBtn.onclick = () => enableEditMode(content);

  } catch (error) {
    readerTitle.textContent = "Chapter Load Failed";
    readerContent.textContent = error.message;
  }
}

function enableEditMode(content) {
  isEditing = true;
  readerContent.style.display = "none";
  readerEditor.style.display = "block";
  readerEditor.value = content;

  editChapterBtn.style.display = "none";
  saveChapterBtn.style.display = "inline-block";

  saveChapterBtn.onclick = saveChapter;
}

async function saveChapter() {
  if (!state.activeChapter) return;
  const content = readerEditor.value;

  try {
    await fetchJSON("/api/chapter/save", {
      method: "POST",
      body: JSON.stringify({
        chapter_id: state.activeChapter,
        content: content
      })
    });

    // Reload to confirm and exit edit mode
    await loadChapter(state.activeChapter);
    alert("Saved successfully!");
  } catch (e) {
    alert("Save failed: " + e.message);
  }
}

async function sendChat() {
  const message = chatInput.value.trim();
  if (!message) return;
  const pendingAgent = findMentionAgentId(message) || "guide";
  const userEntry = {
    id: `local-${Date.now()}`,
    role: "user",
    agent_id: pendingAgent,
    content: message,
    timestamp: Date.now() / 1000,
  };
  state.chat.push(userEntry);
  renderChat();
  chatInput.value = "";
  hideMentionMenu();
  const pendingId = `pending-${Date.now()}`;
  state.chat.push({
    id: pendingId,
    role: "assistant",
    agent_id: pendingAgent,
    content: "",
    timestamp: Date.now() / 1000,
    pending: true,
  });
  renderChat();
  try {
    const reply = await fetchJSON("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message }),
    });
    const pendingIndex = state.chat.findIndex((msg) => msg.id === pendingId);

    // Check for Manual Chat 503 Errors (returned as normal message content)
    // Check for Manual Chat 503 Errors (returned as normal message content)
    if (reply.content && (reply.content.includes("503") || reply.content.includes("overloaded")) && reply.content.includes("失败")) {
      reply.hasRetry = true;
    }

    if (pendingIndex >= 0) {
      state.chat[pendingIndex] = reply;
    } else {
      state.chat.push(reply);
    }
    renderChat();

    // AUTO-FLOW HANDLING DETECTED HERE
    if (reply.trigger_auto_gen) {
      console.log("Auto-gen trigger received from backend");
      // We defer it slightly to let UI render
      setTimeout(() => startAutoGeneration(), 1000);
    }

    // Refresh Tokens after any chat turn (e.g. if files changed)
    try {
      const settings = await fetchJSON("/api/settings");
      state.settings = settings;
      renderProjectMeta();
    } catch (e) { console.error(e); }

  } catch (error) {
    const pendingIndex = state.chat.findIndex((msg) => msg.id === pendingId);
    if (pendingIndex >= 0) {
      state.chat[pendingIndex] = {
        id: `error-${Date.now()}`,
        role: "assistant",
        agent_id: pendingAgent,
        content: `System Error: ${error.message}`,
        timestamp: Date.now() / 1000,
      };
    }
    renderChat();
  }
}

async function retryLastMessage(btn) {
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = "⏳ Waiting (3s)...";
    await new Promise(r => setTimeout(r, 1000));
    btn.innerHTML = "⏳ Waiting (2s)...";
    await new Promise(r => setTimeout(r, 1000));
    btn.innerHTML = "⏳ Waiting (1s)...";
    await new Promise(r => setTimeout(r, 1000));
    btn.innerHTML = "🔄 Retrying...";
  }

  // Find last user message
  const lastUserMsg = [...state.chat].reverse().find(m => m.role === "user");
  if (lastUserMsg && lastUserMsg.content) {
    console.log("Retrying:", lastUserMsg.content);
    await sendChat(lastUserMsg.content, lastUserMsg.agent_id || "guide");
  } else {
    alert("No previous user message found to retry.");
    if (btn) btn.disabled = false;
  }
}

async function retryAutoGen(btn) {
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = "⏳ Cooling down (3s)...";
    await new Promise(r => setTimeout(r, 1000));
    btn.innerHTML = "⏳ Cooling down (2s)...";
    await new Promise(r => setTimeout(r, 1000));
    btn.innerHTML = "⏳ Cooling down (1s)...";
    await new Promise(r => setTimeout(r, 1000));
    btn.innerHTML = "🚀 Starting...";
  }
  window.startAutoGeneration();
}

async function runStep(step) {
  // ... kept as is, though mostly unused if we automate ...
  const payload = { step };
  await fetchJSON("/api/step", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  // Simplified strictly for automation logic if needed
  await refreshChapters();
}

async function refreshChapters() {
  state.chapters = await fetchJSON("/api/preview/chapters");
  renderChapters();
}

async function init() {
  try {
    const agents = await fetchJSON("/api/agents");
    state.agents = agents;
    state.agentMap = Object.fromEntries(agents.map((agent) => [agent.agent_id, agent]));

    renderAgents();
    await refreshProjects();

    // STARTUP LOGIC:
    // Do NOT load chat/settings/models immediately. 
    // Go to Projects view and wait for user selection.
    switchView("projects");

    // If we happen to have a project selected from backend session (reloaded), we can try to hydrate it:
    // But for a "Blank" experience, maybe we check if backend has a project loaded?
    // Let's rely on user action. But if backend has active project, we should populate.
    const settings = await fetchJSON("/api/settings");
    if (settings && settings.project_slug) {
      state.settings = settings;
      state.chat = await fetchJSON("/api/chat");
      state.chapters = await fetchJSON("/api/preview/chapters");
      renderChat();
      renderProjectMeta();
      renderChapters();
      // switchView("create"); // Auto-enter removed to start in Projects
    } else {
      renderProjectMeta(); // Will show "No Project"
    }

  } catch (error) {
    console.error(error);
  }
}

navButtons.forEach((btn) => {
  btn.addEventListener("click", () => switchView(btn.dataset.view));
});

sendBtn.addEventListener("click", sendChat);
chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendChat();
  }
});

chatInput.addEventListener("input", handleMention);
chatInput.addEventListener("click", handleMention);
chatInput.addEventListener("keyup", handleMention);

// Action button handlers
function bindActionButtons() {
  document.querySelectorAll(".edit-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => handleEdit(e.target.dataset.msgId));
  });
  document.querySelectorAll(".continue-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => handleContinue(e.target.dataset.msgId));
  });
  document.querySelectorAll(".rewrite-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => handleRewrite(e.target.dataset.msgId));
  });
  document.querySelectorAll(".auto-write-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => startAutoGeneration());
  });
  document.querySelectorAll(".confirm-setup-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => handleSetupConfirm(e.target));
  });
}

function handleEdit(msgId) {
  const msg = state.chat.find((m) => m.id === msgId);
  if (!msg) return;
  const msgElement = document.querySelector(`[data-msg-id="${msgId}"]`)?.closest(".message");
  if (!msgElement) return;
  const contentEl = msgElement.querySelector(".message-content");
  const originalContent = msg.content;
  contentEl.innerHTML = `
    <textarea class="edit-textarea" rows="10">${originalContent}</textarea>
    <div class="edit-actions">
      <button class="save-edit-btn">Save</button>
      <button class="cancel-edit-btn">Cancel</button>
    </div>
  `;
  contentEl.querySelector(".save-edit-btn").addEventListener("click", () => {
    const newContent = contentEl.querySelector(".edit-textarea").value;
    msg.content = newContent;
    renderChat();
  });
  contentEl.querySelector(".cancel-edit-btn").addEventListener("click", () => {
    renderChat();
  });
}

async function handleContinue(msgId) {
  const msg = state.chat.find((m) => m.id === msgId);
  if (!msg) return;
  chatInput.value = "Please continue generation based on the previous context.";
  await sendChat();
}

async function handleRewrite(msgId) {
  const msg = state.chat.find((m) => m.id === msgId);
  if (!msg) return;
  chatInput.value = "Please rewrite this part to improve it.";
  await sendChat();
}


let isGeneratingAll = false;

async function startAutoGeneration() {
  if (isGeneratingAll) return;
  isGeneratingAll = true;

  // Initial feedback in chat
  state.chat.push({
    id: `sys-${Date.now()}`,
    role: "assistant",
    agent_id: "guide",
    content: "🚀 自动生成已触发，正在为您编写全书... (You can go to Reviews to check progress)",
    timestamp: Date.now() / 1000,
  });
  renderChat();

  let retries = 0;
  try {
    while (true) {
      const pendingId = `pending-gen-${Date.now()}`;

      let res;
      try {
        res = await fetchJSON("/api/auto_generate", { method: "POST" });
        retries = 0; // Reset retries on success
      } catch (fetchErr) {
        // Check for 503 / Overloaded
        if (fetchErr.message && (fetchErr.message.includes("503") || fetchErr.message.includes("model is overloaded"))) {
          state.chat.push({
            id: `err-503-${Date.now()}`,
            role: "assistant",
            agent_id: "guide",
            content: `❌ Service Overloaded (503). Please wait a moment and retry.`,
            hasRetry: true,
            retryAction: "auto_gen",
            timestamp: Date.now() / 1000
          });
          renderChat();
          break; // Stop current loop, let user retry
        }

        // Check for "Unexpected token I" (Internal Server Error text) or similar JSON errors
        if ((fetchErr.message && fetchErr.message.includes("Unexpected token")) || fetchErr.message.includes("JSON")) {
          if (retries < 3) {
            retries++;
            console.warn(`JSON Error detected, retrying (${retries}/3)...`);
            state.chat.push({
              id: `retry-${Date.now()}`,
              role: "assistant",
              agent_id: "guide",
              content: `⚠️ Encountered a format error, retrying (${retries}/3)...`,
              timestamp: Date.now() / 1000
            });
            renderChat();
            await new Promise(r => setTimeout(r, 2000));
            continue; // Retry loop
          }
        }
        throw fetchErr; // Re-throw if not retry-able or max retries reached
      }

      if (res.status === "complete") {
        state.chat.push({
          id: `sys-done-${Date.now()}`,
          role: "assistant",
          agent_id: "guide",
          content: "✅ 全书生成完毕！",
          timestamp: Date.now() / 1000,
        });
        renderChat();
        break;
      }

      if (res.status === "generated") {
        await refreshChapters();

        let label = `Chapter ${res.chapter}`;
        let statusMsg = `第 ${res.chapter} 章生成完毕`;

        if (res.chapter === "Outline") {
          label = "Outline";
          statusMsg = "大纲生成完毕";
        } else if (res.chapter === "Characters") {
          label = "Character Profile";
          statusMsg = "角色档案生成完毕";
        }

        state.chat.push({
          id: `gen-${res.chapter}-${Date.now()}`,
          role: "assistant",
          agent_id: "writer",
          content: `✅ ${label} Generated.\n${(res.content || "").slice(0, 100)}...`,
          timestamp: Date.now() / 1000,
        });

        // Add Host/Guide Confirmation as requested
        state.chat.push({
          id: `stat-${res.chapter}-${Date.now()}`,
          role: "assistant",
          agent_id: "guide",
          content: `${statusMsg}，共 ${(res.content || "").length} 字。正在休息 3 秒...`,
          timestamp: Date.now() / 1000 + 0.1
        });
        renderChat();

        // Refresh Tokens
        try {
          const settings = await fetchJSON("/api/settings");
          state.settings = settings;
          renderProjectMeta();
        } catch (e) { console.error("Token refresh failed", e); }

        // 3s delay to avoid Rate Limit
        await new Promise(r => setTimeout(r, 3000));
      } else if (res.status === "error") {
        // Check for 503 / Overloaded in the backend error message
        if (res.message && (res.message.includes("503") || res.message.includes("model is overloaded"))) {
          state.chat.push({
            id: `err-503-${Date.now()}`,
            role: "assistant",
            agent_id: "guide",
            content: `❌ Service Overloaded (503). Please wait a moment and retry.`,
            hasRetry: true,
            retryAction: "auto_gen",
            timestamp: Date.now() / 1000
          });
        } else {
          state.chat.push({
            id: `err-${Date.now()}`,
            role: "assistant",
            agent_id: "guide",
            content: `❌ Error: ${res.message}`,
            timestamp: Date.now() / 1000,
          });
        }
        renderChat();
        break;
      }
    }
  } catch (err) {
    state.chat.push({
      id: `sys-err-${Date.now()}`,
      role: "assistant",
      agent_id: "guide",
      content: `❌ 批量生成异常终止：${err.message}`,
      timestamp: Date.now() / 1000,
    });
    renderChat();
  } finally {
    isGeneratingAll = false;
  }
}


// Project Management Logic


// Old listeners removed (switch/create)


async function handleProjectSwitch(slug) {
  try {
    await fetchJSON("/api/projects/switch", {
      method: "POST",
      body: JSON.stringify({ slug })
    });
    // Reload everything
    await init();
    alert(`Switched to project: ${slug}`);
    switchView("create"); // Go to chat
  } catch (e) {
    alert("Switch Failed: " + e.message);
  }
}

init();

function handleMention() {
  const cursor = chatInput.selectionStart;
  const text = chatInput.value;
  const atIndex = text.lastIndexOf("@", cursor - 1);
  if (atIndex === -1) {
    hideMentionMenu();
    return;
  }
  if (atIndex > 0 && !/\s/.test(text[atIndex - 1])) {
    hideMentionMenu();
    return;
  }
  const query = text.slice(atIndex + 1, cursor);
  if (/\s/.test(query)) {
    hideMentionMenu();
    return;
  }
  showMentionMenu(query, atIndex, cursor);
}

function showMentionMenu(query, startIndex, cursorIndex) {
  const visibleAgents = state.agents.filter((agent) => state.showBackstage || !agent.hidden);
  const filtered = visibleAgents.filter((agent) => {
    const name = agent.name.toLowerCase();
    const id = agent.agent_id.toLowerCase();
    const q = query.toLowerCase();
    return name.includes(q) || id.includes(q);
  });
  if (!filtered.length) {
    hideMentionMenu();
    return;
  }
  state.mentionStart = { startIndex, cursorIndex };
  mentionMenu.innerHTML = "";
  filtered.forEach((agent) => {
    const item = document.createElement("div");
    item.className = "mention-item";
    item.innerHTML = `
      <div class="avatar" style="background: ${agent.color}">${agent.name.slice(0, 1)}</div>
      <div>
        <div>${agent.name}</div>
        <small>${agent.description}</small>
      </div>
    `;
    item.addEventListener("click", () => insertMention(agent.name));
    mentionMenu.appendChild(item);
  });
  mentionMenu.classList.add("active");
}

function hideMentionMenu() {
  mentionMenu.classList.remove("active");
  state.mentionStart = null;
}

function insertMention(name) {
  if (!state.mentionStart) return;
  const { startIndex, cursorIndex } = state.mentionStart;
  const text = chatInput.value;
  const before = text.slice(0, startIndex);
  const after = text.slice(cursorIndex);
  const mentionText = `@${name} `;
  chatInput.value = `${before}${mentionText}${after}`;
  const newCursor = before.length + mentionText.length;
  chatInput.setSelectionRange(newCursor, newCursor);
  chatInput.focus();
  hideMentionMenu();
}

function findMentionAgentId(message) {
  const hits = state.agents.map((agent) => {
    const nameIndex = message.indexOf(`@${agent.name}`);
    const idIndex = message.indexOf(`@${agent.agent_id}`);
    const index = Math.min(
      nameIndex === -1 ? Infinity : nameIndex,
      idIndex === -1 ? Infinity : idIndex
    );
    return { agent, index };
  });
  const best = hits.filter((hit) => hit.index !== Infinity).sort((a, b) => a.index - b.index)[0];
  return best ? best.agent.agent_id : null;
}
