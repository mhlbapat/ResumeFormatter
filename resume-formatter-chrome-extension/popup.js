// Popup script: lets the user paste a job description, then asks the background
// script to generate a tailored resume, download it, and open it in a new tab.

const statusEl = document.getElementById("status");
const spinnerEl = document.getElementById("spinner");
const retryEl = document.getElementById("retry");
const jobTextEl = document.getElementById("jobText");
const generateBtn = document.getElementById("generateBtn");

function setStatus(msg, { loading = false, showRetry = false } = {}) {
  statusEl.textContent = msg;
  spinnerEl.style.display = loading ? "inline-block" : "none";
  retryEl.style.display = showRetry ? "inline" : "none";
}

function requestGeneration() {
  const text = (jobTextEl.value || "").trim();
  if (!text) {
    setStatus("Please paste a job description before generating.", { loading: false, showRetry: false });
    return;
  }

  setStatus("Generating tailored resume...", { loading: true, showRetry: false });
  generateBtn.disabled = true;

  chrome.runtime.sendMessage(
    { type: "GENERATE_RESUME_FROM_TEXT", description: text },
    (resp) => {
      if (chrome.runtime.lastError) {
        setStatus(`Extension error: ${chrome.runtime.lastError.message}`, { loading: false, showRetry: true });
        generateBtn.disabled = false;
        return;
      }
      if (!resp) {
        setStatus("No response from background script.", { loading: false, showRetry: true });
        generateBtn.disabled = false;
        return;
      }
      if (resp.error) {
        setStatus(`Error: ${resp.error}`, { loading: false, showRetry: true });
        generateBtn.disabled = false;
        return;
      }

      const labelParts = [];
      if (resp.jobTitle) labelParts.push(resp.jobTitle);
      if (resp.company) labelParts.push(resp.company);
      const label = labelParts.join(" at ");
      setStatus(label ? `Downloaded & opened resume for ${label}.` : "Downloaded & opened resume.", {
        loading: false,
        showRetry: false
      });
      generateBtn.disabled = false;
    }
  );
}

document.addEventListener("DOMContentLoaded", () => {
  setStatus("Paste a job description and click Generate & Download.", { loading: false, showRetry: false });

  generateBtn.addEventListener("click", () => {
    requestGeneration();
  });

  retryEl.addEventListener("click", () => {
    requestGeneration();
  });



  // Prevent scrolling the entire popup; only allow scrolling inside the textarea.
  // This stops the outer page from moving when you use the mouse wheel,
  // while keeping the inner jobText scrollable.
  document.addEventListener(
    "wheel",
    (event) => {
      const target = event.target;
      // If the wheel event is inside the textarea, let the textarea handle its own scrolling.
      if (jobTextEl.contains(target)) {
        const atTop = jobTextEl.scrollTop === 0;
        const atBottom =
          Math.ceil(jobTextEl.scrollTop + jobTextEl.clientHeight) >= jobTextEl.scrollHeight;
        const scrollingUp = event.deltaY < 0;
        const scrollingDown = event.deltaY > 0;

        // If we're trying to scroll beyond the textarea's bounds, block it so it
        // doesn't propagate to the outer document.
        if ((scrollingUp && atTop) || (scrollingDown && atBottom)) {
          event.preventDefault();
        }
        // Otherwise, allow the textarea to scroll normally.
        return;
      }

      // For any wheel event outside the textarea, block scrolling entirely.
      event.preventDefault();
    },
    { passive: false }
  );
});
