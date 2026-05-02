document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("voting-form");
  const submitBtn = document.getElementById("submit-btn");
  const resultsContainer = document.getElementById("results-container");
  const judgeSection = document.getElementById("judge-section");

  const outputs = {
    humorous: document.getElementById("result-humorous"),
    professional: document.getElementById("result-professional"),
    urgent: document.getElementById("result-urgent"),
    judge: document.getElementById("result-judge"),
  };

  const accumulated = { humorous: "", professional: "", urgent: "", judge: "" };

  function renderMarkdown(el, text) {
    if (typeof marked !== "undefined" && typeof DOMPurify !== "undefined") {
      el.innerHTML = DOMPurify.sanitize(marked.parse(text));
    } else {
      el.textContent = text;
    }
  }

  function reset() {
    for (const key of Object.keys(accumulated)) accumulated[key] = "";
    for (const el of Object.values(outputs)) if (el) el.innerHTML = "";
    judgeSection.style.display = "none";
    resultsContainer.style.display = "none";
    submitBtn.disabled = true;
    submitBtn.textContent = "Running…";
  }

  function done() {
    submitBtn.disabled = false;
    submitBtn.textContent = "Run Agent";
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const prompt = new FormData(form).get("prompt")?.trim();
    if (!prompt) return;

    reset();
    resultsContainer.style.display = "block";

    const handler = new StreamHandler(
      `/stream_voting?prompt=${encodeURIComponent(prompt)}`,
      (data) => {
        if (data.type !== "step") return;
        const { agent, content } = data;
        if (!outputs[agent]) return;

        if (agent === "judge" && judgeSection.style.display === "none") {
          judgeSection.style.display = "block";
        }

        accumulated[agent] += content;
        renderMarkdown(outputs[agent], accumulated[agent]);
      },
      done,
      (err) => { console.error("Stream error:", err); done(); },
    );

    handler.start();
  });
});
