(function () {
  if (window.__neshoraTimerInitialized) {
    return;
  }
  window.__neshoraTimerInitialized = true;
  const config = window.NeshoraTimer;
  if (!config) {
    throw new Error("Timer configuration is unavailable.");
  }
  const display = document.getElementById("timer-display");
  const status = document.getElementById("timer-status");
  const subject = document.getElementById("timer-subject");
  const select = document.getElementById("subject-select");
  const taskSelect = document.getElementById("task-select");
  const error = document.getElementById("timer-error");
  const start = document.getElementById("start-button");
  const pause = document.getElementById("pause-button");
  const resume = document.getElementById("resume-button");
  const finish = document.getElementById("finish-button");
  const modal = document.getElementById("subject-modal");
  const modalTitle = document.getElementById("subject-modal-title");
  const modalEyebrow = document.getElementById("subject-modal-eyebrow");
  const modalInput = document.getElementById("custom-subject-name");
  const modalError = document.getElementById("subject-modal-error");
  const modalSuccess = document.getElementById("subject-modal-success");
  const saveSubject = document.getElementById("save-subject-button");
  const customSubjectList = document.getElementById("custom-subject-list");
  let active = config.active;
  let elapsed = active ? active.elapsed_seconds : 0;
  let serverOffset = active ? active.server_time * 1000 - Date.now() : 0;
  let requestInFlight = false;
  let editingSubjectId = null;

  function format(seconds) {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return [hours, minutes].map(value => String(value).padStart(2, "0")).join(":");
  }

  function render() {
    const liveSeconds = active && active.status === "active"
      ? elapsed + Math.max(0, Math.floor((Date.now() + serverOffset - active.resumed_at) / 1000))
      : elapsed;
    display.textContent = format(liveSeconds);
    status.textContent = active
      ? (active.status === "active" ? "In progress" : "Paused")
      : "Ready to focus";
    subject.textContent = active ? active.subject : "Choose a subject to begin";
    start.hidden = Boolean(active);
    pause.hidden = !active || active.status !== "active";
    resume.hidden = !active || active.status !== "paused";
    finish.hidden = !active;
    select.disabled = Boolean(active);
    taskSelect.disabled = Boolean(active);
    start.disabled = requestInFlight;
    pause.disabled = requestInFlight;
    resume.disabled = requestInFlight;
    finish.disabled = requestInFlight;
  }

  async function request(path, method, body) {
    error.textContent = "";
    requestInFlight = true;
    render();
    try {
      const response = await fetch(path, {
        method,
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": config.csrfToken
        },
        body: body ? JSON.stringify(body) : undefined
      });
      const text = await response.text();
      let data;
      try {
        data = text ? JSON.parse(text) : {};
      } catch {
        throw new Error("The server returned an invalid response.");
      }
      if (!response.ok) {
        throw new Error(data.error || "The request failed.");
      }
      return data;
    } finally {
      requestInFlight = false;
      render();
    }
  }

  function setActive(data) {
    active = data.active_session;
    elapsed = active ? active.elapsed_seconds : 0;
    if (active) {
      serverOffset = active.server_time * 1000 - Date.now();
    }
    render();
  }

  function closeSubjectModal() {
    modal.hidden = true;
    modalError.textContent = "";
    modalSuccess.textContent = "";
    modalInput.value = "";
    editingSubjectId = null;
  }

  function openSubjectModal(subjectId, name) {
    editingSubjectId = subjectId || null;
    modalTitle.textContent = subjectId ? "Rename subject" : "Add a new subject";
    modalEyebrow.textContent = subjectId ? "UPDATE YOUR SUBJECT" : "PERSONALIZE YOUR SPACE";
    modalInput.value = name || "";
    modalError.textContent = "";
    modalSuccess.textContent = "";
    modal.hidden = false;
    modalInput.focus();
  }

  function refreshSubjectManagement() {
    customSubjectList.innerHTML = "";
    select.querySelectorAll("option[data-custom-subject-id], option[data-add-subject]")
      .forEach(option => option.remove());
    const addOption = document.createElement("option");
    addOption.value = "__add_subject__";
    addOption.dataset.addSubject = "true";
    addOption.textContent = "+ Add New Subject";
    select.appendChild(addOption);
    config.subjectRecords = config.subjectRecords || [];
    if (!config.subjectRecords.length) {
      customSubjectList.innerHTML = "<small>No custom subjects yet.</small>";
      return;
    }
    config.subjectRecords.forEach(item => {
      const option = document.createElement("option");
      option.value = item.name;
      option.dataset.customSubjectId = item.id;
      option.textContent = item.name;
      select.insertBefore(option, addOption);
      const button = document.createElement("button");
      button.type = "button";
      button.className = "subject-manage";
      button.dataset.subjectId = item.id;
      button.dataset.subjectName = item.name;
      button.innerHTML = `${item.name} <span>edit / delete</span>`;
      customSubjectList.appendChild(button);
    });
  }

  async function saveSubjectValue() {
    if (requestInFlight) return;
    const name = modalInput.value.trim();
    if (!name) {
      modalError.textContent = "Subject name cannot be empty.";
      return;
    }
    saveSubject.disabled = true;
    try {
      const path = editingSubjectId ? `/subjects/${editingSubjectId}` : "/subjects";
      const data = await request(path, editingSubjectId ? "PATCH" : "POST", {name});
      const saved = data.subject;
      config.subjectRecords = config.subjectRecords || [];
      if (editingSubjectId) {
        const index = config.subjectRecords.findIndex(item => item.id === saved.id);
        if (index >= 0) config.subjectRecords[index] = saved;
      } else {
        const duplicate = config.subjectRecords.some(item => item.id === saved.id);
        if (!duplicate) config.subjectRecords.push(saved);
      }
      refreshSubjectManagement();
      select.value = saved.name;
      modalError.textContent = "";
      modalSuccess.textContent = "Subject saved successfully.";
      setTimeout(closeSubjectModal, 500);
    } catch (exception) {
      modalError.textContent = exception.message;
    } finally {
      saveSubject.disabled = false;
    }
  }

  start.addEventListener("click", async () => {
    if (requestInFlight || active) return;
    try {
      const data = await request("/timer/start", "POST", {
        subject: select.value,
        task_id: taskSelect.value || null
      });
      setActive(data);
    } catch (exception) {
      error.textContent = exception.message;
    }
  });
  select.addEventListener("change", () => {
    if (select.value === "__add_subject__") {
      select.value = "";
      openSubjectModal();
    }
  });
  document.querySelectorAll("[data-close-subject-modal]").forEach(element => {
    element.addEventListener("click", closeSubjectModal);
  });
  customSubjectList.addEventListener("click", event => {
    const button = event.target.closest(".subject-manage");
    if (!button) return;
    const action = window.prompt(
      `Type "rename" to rename ${button.dataset.subjectName}, or "delete" to delete it.`
    );
    if (action === "rename") {
      openSubjectModal(Number(button.dataset.subjectId), button.dataset.subjectName);
    } else if (action === "delete" &&
      window.confirm(`Delete ${button.dataset.subjectName}? Study history will remain safe.`)) {
      request(`/subjects/${button.dataset.subjectId}`, "DELETE")
        .then(() => {
          config.subjectRecords = config.subjectRecords.filter(
            item => item.id !== Number(button.dataset.subjectId)
          );
          if (select.value === button.dataset.subjectName) select.value = "";
          refreshSubjectManagement();
        })
        .catch(exception => {
          error.textContent = exception.message;
        });
    }
  });
  saveSubject.addEventListener("click", saveSubjectValue);
  modalInput.addEventListener("keydown", event => {
    if (event.key === "Enter") saveSubjectValue();
    if (event.key === "Escape") closeSubjectModal();
  });
  pause.addEventListener("click", async () => {
    if (requestInFlight || !active) return;
    try {
      setActive(await request(`/timer/${active.id}/pause`, "POST"));
    } catch (exception) {
      error.textContent = exception.message;
    }
  });
  resume.addEventListener("click", async () => {
    if (requestInFlight || !active) return;
    try {
      setActive(await request(`/timer/${active.id}/resume`, "POST"));
    } catch (exception) {
      error.textContent = exception.message;
    }
  });
  finish.addEventListener("click", async () => {
    if (requestInFlight || !active) return;
    try {
      const result = await request(`/timer/${active.id}/finish`, "POST");
      if (result.assessment_required && result.assessment_url) {
        window.location.href = result.assessment_url;
      } else {
        window.location.reload();
      }
    } catch (exception) {
      error.textContent = exception.message;
    }
  });

  setInterval(render, 1000);
  render();
  refreshSubjectManagement();
  if (window.Chart) {
    new Chart(document.getElementById("weekly-chart"), {
      type: "bar",
      data: {
        labels: config.weekly.map(day => day.label),
        datasets: [{
          label: "Minutes",
          data: config.weekly.map(day => Math.round(day.seconds / 60)),
          backgroundColor: "#b8d8ba",
          borderColor: "#526b55",
          borderWidth: 1,
          borderRadius: 8
        }]
      },
      options: {
        plugins: {legend: {display: false}},
        scales: {y: {beginAtZero: true, ticks: {precision: 0}}}
      }
    });
  }
}());
