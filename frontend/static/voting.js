document.addEventListener("DOMContentLoaded", () => {
	const form = document.getElementById("voting-form");
	const submitBtn = document.getElementById("submit-btn");
	const resultsContainer = document.getElementById("results-container");
	const judgeSection = document.getElementById("judge-section");
	const feedbackRow = document.getElementById("feedback-row");

	const errorBanner = document.getElementById("error-banner");

	const outputs = {
		humorous: document.getElementById("result-humorous"),
		professional: document.getElementById("result-professional"),
		urgent: document.getElementById("result-urgent"),
		judge: document.getElementById("result-judge"),
	};

	const accumulated = { humorous: "", professional: "", urgent: "", judge: "" };
	let currentPrompt = "";
	let currentSessionId = null;
	let currentUserId = "demo-user";

	function renderMarkdown(el, text) {
		if (typeof marked !== "undefined" && typeof DOMPurify !== "undefined") {
			el.innerHTML = DOMPurify.sanitize(marked.parse(text, { breaks: true }));
		} else {
			el.textContent = text;
		}
	}

	const resultCards = document.querySelectorAll(".result-card");
	const parallelCards = document.querySelectorAll("#parallel-section .result-card");
	const judgeCard = document.querySelector("#judge-section .result-card");
	let activeHandler = null;

	function reset() {
		for (const key of Object.keys(accumulated)) accumulated[key] = "";
		for (const el of Object.values(outputs)) if (el) el.innerHTML = "";
		judgeSection.classList.remove("visible");
		resultsContainer.classList.remove("visible");
		feedbackRow.classList.remove("visible");
		errorBanner.classList.remove("visible");
		errorBanner.textContent = "";
		for (const btn of feedbackRow.querySelectorAll(".feedback-btn")) {
			btn.classList.remove("selected-agree", "selected-disagree");
			btn.disabled = false;
		}
		if (activeHandler) {
			activeHandler.close();
			activeHandler = null;
		}
		for (const card of resultCards) card.classList.remove("animate-in");
		submitBtn.disabled = true;
		submitBtn.textContent = "Running…";
	}

	function extractWinner(judgeText) {
		const match = judgeText.match(/\*\*Winner:\*\*\s*(HUMOROUS|PROFESSIONAL|URGENT)/i);
		return match ? match[1].toLowerCase() : null;
	}

	function done() {
		submitBtn.disabled = false;
		submitBtn.textContent = "Run Agent";
		if (accumulated.judge) feedbackRow.classList.add("visible");
	}

	feedbackRow.addEventListener("click", async (e) => {
		const btn = e.target.closest(".feedback-btn");
		if (!btn || btn.disabled) return;

		const agreed = btn.dataset.agreed === "true";
		const style = extractWinner(accumulated.judge);

		for (const b of feedbackRow.querySelectorAll(".feedback-btn")) b.disabled = true;
		btn.classList.add(agreed ? "selected-agree" : "selected-disagree");

		try {
			await fetch("/feedback", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					prompt: currentPrompt,
					style,
					agreed,
					session_id: currentSessionId,
					user_id: currentUserId,
				}),
			});
		} catch (err) {
			console.error("Feedback error:", err);
		}
	});

	form.addEventListener("submit", (e) => {
		e.preventDefault();
		const prompt = new FormData(form).get("prompt")?.trim();
		if (!prompt) return;

		currentPrompt = prompt;
		currentSessionId = null;
		reset();
		resultsContainer.classList.add("visible");
		for (const card of parallelCards) card.classList.add("animate-in");

		activeHandler = new StreamHandler(
			`/stream_voting?prompt=${encodeURIComponent(prompt)}`,
			(data) => {
				if (data.type === "session") {
					currentSessionId = data.session_id;
					currentUserId = data.user_id;
					return;
				}
				if (data.type === "blocked" || data.type === "error") {
					errorBanner.textContent = data.message;
					errorBanner.classList.add("visible");
					resultsContainer.classList.remove("visible");
					done();
					return;
				}
				if (data.type !== "step") return;
				const { agent, content } = data;
				if (!outputs[agent]) return;

				if (agent === "judge" && !judgeSection.classList.contains("visible")) {
					judgeSection.classList.add("visible");
					if (judgeCard) judgeCard.classList.add("animate-in");
				}

				accumulated[agent] += content;
				renderMarkdown(outputs[agent], accumulated[agent]);
			},
			done,
			(err) => {
				console.error("Stream error:", err);
				done();
			}
		);

		activeHandler.start();
	});
});
