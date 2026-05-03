/** biome-ignore-all lint/correctness/noUnusedVariables: used in voting.js */
class StreamHandler {
	constructor(url, onMessage, onComplete, onError) {
		this.url = url;
		this.onMessage = onMessage;
		this.onComplete = onComplete;
		this.onError = onError;
		this.eventSource = null;
	}

	start() {
		try {
			this.eventSource = new EventSource(this.url);
			this.eventSource.onmessage = (event) => {
				let data;
				try {
					data = JSON.parse(event.data);
				} catch (e) {
					console.error("SSE parse error:", e, event.data);
					this.close();
					if (this.onError) this.onError(e);
					return;
				}
				this.onMessage(data);
				if (data.type === "complete") {
					this.close();
					if (this.onComplete) this.onComplete();
				}
			};
			this.eventSource.onerror = (error) => {
				console.error("SSE Error:", error);
				this.close();
				if (this.onError) this.onError(error);
			};
		} catch (error) {
			console.error("StreamHandler setup error:", error);
			if (this.onError) this.onError(error);
		}
	}

	close() {
		if (this.eventSource) {
			this.eventSource.close();
			this.eventSource = null;
		}
	}
}
