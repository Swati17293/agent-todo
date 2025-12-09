const API_BASE = "/api"; // backend is on same server

// ---------- Global Agent State ----------

let currentState = null;       // Latest AgentState from backend
let activeIndex = 0;           // Index into pending tasks
let hasPendingChanges = false; // Whether textarea differs from saved version

// Active Task UI refs
let activeTaskLabel = null;
let activeTaskTextarea = null;
let activeTaskPrevBtn = null;
let activeTaskNextBtn = null;
let activeTaskRegenerateBtn = null;
let activeTaskExecuteBtn = null;
let activeTaskCancelBtn = null;
let activeTaskAcceptBtn = null;
let activeTaskRejectBtn = null;

// ---------- Shared helpers ----------

function setMessage(msg) {
  const el = document.getElementById("message");
  if (!el) return;

  const text = msg || "";
  el.textContent = text;
  el.style.display = text ? "block" : "none";
}

function getErrorMessage(err, fallback) {
  if (
    err &&
    err.response &&
    err.response.data &&
    typeof err.response.data.detail === "string"
  ) {
    return err.response.data.detail;
  }
  return fallback;
}

function renderTasks(tasks) {
  const list = document.getElementById("taskList");
  if (!list) return;

  list.innerHTML = "";

  if (!tasks || tasks.length === 0) {
    list.innerHTML = `
      <li class="list-group-item">
        <span class="task-text">No tasks yet.</span><br />
        <small>Enter your goal and generate a plan to begin</small>
      </li>
    `;
    return;
  }

  tasks.forEach((t) => {
    const li = document.createElement("li");
    li.className = "list-group-item";

    const status = t.status || "pending";

    let badgeClass = "bg-secondary";
    if (status === "done") {
      badgeClass = "bg-success";
    } else if (status === "failed") {
      badgeClass = "bg-danger";
    } else if (status === "needs_follow_up") {
      badgeClass = "bg-warning";
    } else if (status === "cancelled") {
      // Clear red badge for cancelled tasks
      badgeClass = "bg-danger";
    }

    const title = t.title || `Task ${t.id}`;
    const description = t.description || "";

    li.innerHTML = `
      <div class="d-flex justify-content-between align-items-center">
        <div>
          <strong>[${t.id}] ${title}</strong><br />
          <small>${description}</small>
        </div>
        <span class="badge ${badgeClass}">${status}</span>
      </div>
    `;

    list.appendChild(li);
  });
}

/**
 * Render combined task overview + execution log into the trace box.
 *
 * Tasks:
 * [1] Clarify the goal (pending)
 * [2] Draft structure (done)
 * [3] Implement website (needs_follow_up)
 * [4] Deploy site (cancelled)
 *
 * -------------------------
 * Execution log:
 * ...
 */
function renderTrace(historyFromCaller) {
  const traceBox = document.getElementById("traceBox");
  if (!traceBox) return;

  const tasks =
    currentState && Array.isArray(currentState.tasks)
      ? currentState.tasks
      : [];

  const history =
    currentState && Array.isArray(currentState.history)
      ? currentState.history
      : Array.isArray(historyFromCaller)
      ? historyFromCaller
      : [];

  const hasTasks = tasks.length > 0;
  const hasHistory = history.length > 0;

  if (!hasTasks && !hasHistory) {
    traceBox.textContent = "No tasks or execution yet.";
    return;
  }

  let tasksText = "";
  if (hasTasks) {
    tasksText = tasks
      .map((t) => {
        const status = t.status || "pending";
        const title = t.title || `Task ${t.id}`;
        return `[${t.id}] ${title} (${status})`;
      })
      .join("\n");
  } else {
    tasksText = "No tasks planned yet.";
  }

  let historyText = "";
  if (hasHistory) {
    // Each history entry already contains its own separator line.
    historyText = history.join("\n\n");
  } else {
    historyText = "No execution yet.";
  }

  traceBox.textContent =
    "Tasks:\n" +
    tasksText +
    "\n\n-------------------------\n\n" +
    "Execution log:\n" +
    historyText;
}

// ---------- Active Task Helpers (Confirm mode) ----------

function getActiveTasks() {
  if (!currentState || !Array.isArray(currentState.tasks)) return [];
  return currentState.tasks.filter((t) => t.status === "pending");
}

function getActiveTask() {
  const activeTasks = getActiveTasks();
  if (activeTasks.length === 0) return null;

  if (activeIndex < 0) activeIndex = 0;
  if (activeIndex >= activeTasks.length) activeIndex = activeTasks.length - 1;
  return activeTasks[activeIndex];
}

function getSavedTextForTask(task) {
  if (!task) return "";
  const title = task.title || `Task ${task.id}`;
  const description = task.description || "";
  return description ? `${title}\n${description}` : title;
}

function parseTaskText(text, fallbackTitle) {
  const raw = text || "";
  const lines = raw.split("\n");
  const firstLine = (lines.shift() || "").trim();
  const title = firstLine || fallbackTitle || "";
  const description = lines.join("\n").trim();
  return { title, description };
}

function setButtonEnabled(btn, enabled) {
  if (!btn) return;
  btn.disabled = !enabled;
}

function showButton(btn) {
  if (!btn) return;
  btn.classList.remove("d-none");
  btn.style.display = "";
}

function hideButton(btn) {
  if (!btn) return;
  btn.classList.add("d-none");
  btn.style.display = "none";
}

function disableAllActiveTaskButtons() {
  [
    activeTaskPrevBtn,
    activeTaskNextBtn,
    activeTaskRegenerateBtn,
    activeTaskExecuteBtn,
    activeTaskCancelBtn,
    activeTaskAcceptBtn,
    activeTaskRejectBtn,
  ].forEach((btn) => setButtonEnabled(btn, false));
}

function syncActiveIndexToTaskId(taskId) {
  const activeTasks = getActiveTasks();
  const idx = activeTasks.findIndex((t) => t.id === taskId);
  if (idx >= 0) {
    activeIndex = idx;
  } else {
    activeIndex = 0;
  }
}

function enterDirtyState() {
  hasPendingChanges = true;

  showButton(activeTaskAcceptBtn);
  showButton(activeTaskRejectBtn);
  setButtonEnabled(activeTaskAcceptBtn, true);
  setButtonEnabled(activeTaskRejectBtn, true);

  setButtonEnabled(activeTaskPrevBtn, false);
  setButtonEnabled(activeTaskNextBtn, false);
  setButtonEnabled(activeTaskRegenerateBtn, false);
  setButtonEnabled(activeTaskExecuteBtn, false);
  setButtonEnabled(activeTaskCancelBtn, false);
}

function leaveDirtyState() {
  hasPendingChanges = false;
  updateActiveTaskUI();
}

function updateActiveTaskUI() {
  if (!activeTaskLabel || !activeTaskTextarea) {
    return;
  }

  if (!currentState || currentState.mode !== "confirm") {
    activeTaskLabel.textContent = "No pending tasks.";
    activeTaskTextarea.value = "";
    activeTaskTextarea.disabled = true;

    disableAllActiveTaskButtons();
    hideButton(activeTaskAcceptBtn);
    hideButton(activeTaskRejectBtn);
    hasPendingChanges = false;
    activeIndex = 0;
    return;
  }

  const activeTasks = getActiveTasks();
  if (activeTasks.length === 0) {
    activeTaskLabel.textContent =
      "No pending tasks. All tasks are terminal.";
    activeTaskTextarea.value = "";
    activeTaskTextarea.disabled = true;

    disableAllActiveTaskButtons();
    hideButton(activeTaskAcceptBtn);
    hideButton(activeTaskRejectBtn);
    hasPendingChanges = false;
    activeIndex = 0;
    return;
  }

  const task = getActiveTask();
  if (!task) {
    activeTaskLabel.textContent =
      "No pending tasks. All tasks are terminal.";
    activeTaskTextarea.value = "";
    activeTaskTextarea.disabled = true;
    disableAllActiveTaskButtons();
    hideButton(activeTaskAcceptBtn);
    hideButton(activeTaskRejectBtn);
    hasPendingChanges = false;
    activeIndex = 0;
    return;
  }

  activeTaskLabel.textContent = `Active pending task (${activeIndex + 1} of ${
    activeTasks.length
  })`;

  const savedText = getSavedTextForTask(task);

  if (!hasPendingChanges) {
    activeTaskTextarea.value = savedText;
  }
  activeTaskTextarea.disabled = false;

  hideButton(activeTaskAcceptBtn);
  hideButton(activeTaskRejectBtn);
  setButtonEnabled(activeTaskAcceptBtn, false);
  setButtonEnabled(activeTaskRejectBtn, false);

  setButtonEnabled(activeTaskPrevBtn, activeIndex > 0);
  setButtonEnabled(
    activeTaskNextBtn,
    activeIndex < activeTasks.length - 1
  );
  setButtonEnabled(activeTaskRegenerateBtn, true);
  setButtonEnabled(activeTaskExecuteBtn, true);
  setButtonEnabled(activeTaskCancelBtn, true);
}

// ---------- Backend interaction: Plan (no global Execute) ----------

async function planTasks() {
  const goalInput = document.getElementById("goal");
  const modeSelect = document.getElementById("mode");
  const providerSelect = document.getElementById("provider");
  const planBtn = document.getElementById("planBtn");

  if (!goalInput || !modeSelect || !providerSelect || !planBtn) {
    console.error("Some UI elements are missing.");
    return;
  }

  const goal = goalInput.value.trim();
  const mode = modeSelect.value;
  const provider = providerSelect.value;

  if (!goal) {
    setMessage("Please enter a goal first.");
    return;
  }

  planBtn.disabled = true;
  setMessage("Planning tasks...");

  try {
    const resp = await axios.post(`${API_BASE}/plan`, {
      goal,
      mode,
      provider,
    });

    currentState = resp.data || null;

    if (!currentState) {
      throw new Error("Empty state from /api/plan");
    }

    renderTasks(currentState.tasks);
    renderTrace(currentState.history);

    activeIndex = 0;
    hasPendingChanges = false;
    updateActiveTaskUI();

    if (mode === "auto") {
      setMessage("Plan created and executed.");
    } else {
      setMessage(
        "Plan created. Review and run tasks from the Planned Tasks panel."
      );
    }
  } catch (err) {
    console.error(err);
    setMessage(getErrorMessage(err, "Error while planning tasks."));
  } finally {
    planBtn.disabled = false;
  }
}

// ---------- Backend interaction: Task-level actions (Confirm mode) ----------

async function handleAcceptChanges() {
  if (!currentState || currentState.mode !== "confirm") return;
  if (!hasPendingChanges) return;

  const task = getActiveTask();
  if (!task) return;

  const textareaValue = activeTaskTextarea ? activeTaskTextarea.value : "";
  const { title, description } = parseTaskText(textareaValue, task.title);

  setButtonEnabled(activeTaskAcceptBtn, false);
  setButtonEnabled(activeTaskRejectBtn, false);
  setMessage("Updating task...");

  try {
    const resp = await axios.post(`${API_BASE}/update_task`, {
      task_id: task.id,
      title,
      description,
    });

    currentState = resp.data || null;
    if (!currentState) throw new Error("Empty state from /api/update_task");

    syncActiveIndexToTaskId(task.id);

    renderTasks(currentState.tasks);
    renderTrace(currentState.history);

    hasPendingChanges = false;
    updateActiveTaskUI();

    setMessage("Task updated.");
  } catch (err) {
    console.error(err);
    setMessage(getErrorMessage(err, "Error while updating task."));
    setButtonEnabled(activeTaskAcceptBtn, true);
    setButtonEnabled(activeTaskRejectBtn, true);
  }
}

function handleRejectChanges() {
  if (!currentState || currentState.mode !== "confirm") return;
  if (!hasPendingChanges) return;

  const task = getActiveTask();
  if (!task) return;

  const savedText = getSavedTextForTask(task);
  if (activeTaskTextarea) {
    activeTaskTextarea.value = savedText;
  }

  leaveDirtyState();
  setMessage("Changes discarded.");
}

async function handleRegenerateTask() {
  if (!currentState || currentState.mode !== "confirm") return;
  if (hasPendingChanges) return;

  const task = getActiveTask();
  if (!task) return;

  disableAllActiveTaskButtons();
  setMessage("Regenerating task...");

  try {
    const resp = await axios.post(`${API_BASE}/regenerate_task`, {
      task_id: task.id,
    });

    const nextState = resp.data || null;
    if (!nextState || !Array.isArray(nextState.tasks)) {
      throw new Error("Empty or invalid state from /api/regenerate_task");
    }

    const updatedTask =
      nextState.tasks.find((t) => t.id === task.id) || task;

    if (activeTaskTextarea && updatedTask) {
      const newText = getSavedTextForTask(updatedTask);
      activeTaskTextarea.value = newText;
    }

    enterDirtyState();
    setMessage(
      "Task regenerated. Review and accept or reject the changes."
    );
  } catch (err) {
    console.error(err);
    setMessage("Regeneration failed. Please try again.");
    hasPendingChanges = false;
    updateActiveTaskUI();
  }
}

async function handleExecuteSingleTask() {
  if (!currentState || currentState.mode !== "confirm") return;
  if (hasPendingChanges) return;

  const task = getActiveTask();
  if (!task) return;

  disableAllActiveTaskButtons();
  setMessage(`Executing task [${task.id}]...`);

  try {
    const resp = await axios.post(`${API_BASE}/execute_task`, {
      task_id: task.id,
    });

    currentState = resp.data || null;
    if (!currentState) throw new Error("Empty state from /api/execute_task");

    renderTasks(currentState.tasks);
    renderTrace(currentState.history);

    const tasks = currentState.tasks || [];
    const pending = tasks.filter((t) => t.status === "pending");

    if (pending.length === 0) {
      activeIndex = 0;
      hasPendingChanges = false;
      updateActiveTaskUI();
      setMessage("Task executed. No pending tasks remain.");
      return;
    }

    let nextPending = pending[0];
    let seenExecuted = false;
    for (const t of tasks) {
      if (t.id === task.id) {
        seenExecuted = true;
        continue;
      }
      if (seenExecuted && t.status === "pending") {
        nextPending = t;
        break;
      }
    }

    const nextIdx = pending.findIndex((t) => t.id === nextPending.id);
    activeIndex = nextIdx >= 0 ? nextIdx : 0;
    hasPendingChanges = false;
    updateActiveTaskUI();

    setMessage("Task executed.");
  } catch (err) {
    console.error(err);
    setMessage(getErrorMessage(err, "Error while executing task."));
    hasPendingChanges = false;
    updateActiveTaskUI();
  }
}

async function handleCancelTask() {
  if (!currentState || currentState.mode !== "confirm") return;
  if (hasPendingChanges) return;

  const task = getActiveTask();
  if (!task) return;

  disableAllActiveTaskButtons();
  setMessage(`Cancelling task [${task.id}]...`);

  try {
    const resp = await axios.post(`${API_BASE}/cancel_task`, {
      task_id: task.id,
    });

    currentState = resp.data || null;
    if (!currentState) throw new Error("Empty state from /api/cancel_task");

    renderTasks(currentState.tasks);
    renderTrace(currentState.history);

    const tasks = currentState.tasks || [];
    const pending = tasks.filter((t) => t.status === "pending");

    if (pending.length === 0) {
      activeIndex = 0;
      hasPendingChanges = false;
      updateActiveTaskUI();
      setMessage("Task cancelled. No pending tasks remain.");
      return;
    }

    let nextPending = pending[0];
    let seenCancelled = false;
    for (const t of tasks) {
      if (t.id === task.id) {
        seenCancelled = true;
        continue;
      }
      if (seenCancelled && t.status === "pending") {
        nextPending = t;
        break;
      }
    }

    const nextIdx = pending.findIndex((t) => t.id === nextPending.id);
    activeIndex = nextIdx >= 0 ? nextIdx : 0;
    hasPendingChanges = false;
    updateActiveTaskUI();

    setMessage("Task cancelled.");
  } catch (err) {
    console.error(err);
    setMessage(getErrorMessage(err, "Error while cancelling task."));
    hasPendingChanges = false;
    updateActiveTaskUI();
  }
}

// ---------- Navigation handlers ----------

function handlePrevTask() {
  if (!currentState || currentState.mode !== "confirm") return;
  if (hasPendingChanges) return;

  const activeTasks = getActiveTasks();
  if (activeTasks.length === 0) return;
  if (activeIndex <= 0) return;

  activeIndex -= 1;
  hasPendingChanges = false;
  updateActiveTaskUI();
}

function handleNextTask() {
  if (!currentState || currentState.mode !== "confirm") return;
  if (hasPendingChanges) return;

  const activeTasks = getActiveTasks();
  if (activeTasks.length === 0) return;
  if (activeIndex >= activeTasks.length - 1) return;

  activeIndex += 1;
  hasPendingChanges = false;
  updateActiveTaskUI();
}

// ---------- Textarea dirty tracking ----------

function handleActiveTaskTextareaInput() {
  if (!currentState || currentState.mode !== "confirm") return;

  const task = getActiveTask();
  if (!task || !activeTaskTextarea) return;

  const savedText = getSavedTextForTask(task);
  const currentText = activeTaskTextarea.value;

  if (!hasPendingChanges && currentText !== savedText) {
    enterDirtyState();
  } else if (hasPendingChanges && currentText === savedText) {
    leaveDirtyState();
  }
}

// ---------- DOMContentLoaded ----------

window.addEventListener("DOMContentLoaded", () => {
  const planBtn = document.getElementById("planBtn");

  if (planBtn) {
    planBtn.addEventListener("click", planTasks);
  }

  activeTaskLabel = document.getElementById("activeTaskLabel");
  activeTaskTextarea = document.getElementById("activeTaskTextarea");
  activeTaskPrevBtn = document.getElementById("activeTaskPrevBtn");
  activeTaskNextBtn = document.getElementById("activeTaskNextBtn");
  activeTaskRegenerateBtn = document.getElementById("activeTaskRegenerateBtn");
  activeTaskExecuteBtn = document.getElementById("activeTaskExecuteBtn");
  activeTaskCancelBtn = document.getElementById("activeTaskCancelBtn");
  activeTaskAcceptBtn = document.getElementById("activeTaskAcceptBtn");
  activeTaskRejectBtn = document.getElementById("activeTaskRejectBtn");

  if (activeTaskLabel) {
    activeTaskLabel.textContent = "No pending tasks.";
  }
  if (activeTaskTextarea) {
    activeTaskTextarea.value = "";
    activeTaskTextarea.disabled = true;
    activeTaskTextarea.addEventListener(
      "input",
      handleActiveTaskTextareaInput
    );
  }

  disableAllActiveTaskButtons();
  hideButton(activeTaskAcceptBtn);
  hideButton(activeTaskRejectBtn);

  if (activeTaskPrevBtn) {
    activeTaskPrevBtn.addEventListener("click", handlePrevTask);
  }
  if (activeTaskNextBtn) {
    activeTaskNextBtn.addEventListener("click", handleNextTask);
  }
  if (activeTaskRegenerateBtn) {
    activeTaskRegenerateBtn.addEventListener("click", handleRegenerateTask);
  }
  if (activeTaskExecuteBtn) {
    activeTaskExecuteBtn.addEventListener("click", handleExecuteSingleTask);
  }
  if (activeTaskCancelBtn) {
    activeTaskCancelBtn.addEventListener("click", handleCancelTask);
  }
  if (activeTaskAcceptBtn) {
    activeTaskAcceptBtn.addEventListener("click", handleAcceptChanges);
  }
  if (activeTaskRejectBtn) {
    activeTaskRejectBtn.addEventListener("click", handleRejectChanges);
  }

  setMessage("Enter a goal, choose mode and provider, then click 'Plan'.");
  renderTasks([]);
  renderTrace([]);
  updateActiveTaskUI();
});
