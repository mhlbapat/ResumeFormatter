// Background/service worker for JobApplicationAgent Chrome extension.
// For the popup flow: receives raw job description text, calls the local backend,
// downloads the generated PDF, and opens it in a new tab.

const API_BASE = "http://localhost:8000";

async function callBackend(description) {
  const body = {
    title: "",
    company: "",
    location: "",
    description
  };

  const res = await fetch(`${API_BASE}/generate_from_text`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Backend error ${res.status}: ${text || res.statusText}`);
  }

  return res.json();
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "GENERATE_RESUME_FROM_TEXT") {
    const description = String(msg.description || "").trim();
    if (!description) {
      sendResponse({ error: "Job description cannot be empty." });
      return true;
    }
    callBackend(description)
      .then((resp) => {
        const pdfUrl = `${API_BASE}${resp.pdf_url}`;
        const jobTitle = (resp.job && resp.job.title) || "";
        const company = (resp.job && resp.job.company) || "";

        const safe = (s) =>
          String(s || "")
            .replace(/\s+/g, "_")
            .replace(/[^A-Za-z0-9_\-]/g, "")
            .slice(0, 60);
        const baseNameParts = ["Mehul_Bapat", safe(company), safe(jobTitle)].filter(Boolean);
        const filename = `${baseNameParts.join("_") || "Mehul_Bapat_Resume"}.pdf`;

        // Download to the user's Downloads folder.
        chrome.downloads.download(
          {
            url: pdfUrl,
            filename,
            saveAs: false
          },
          () => {}
        );

        // Open the PDF in a new tab in the same window as the popup tab, if available.
        const senderTab = _sender && _sender.tab;
        const createOpts = senderTab && senderTab.windowId
          ? { url: pdfUrl, windowId: senderTab.windowId }
          : { url: pdfUrl };
        chrome.tabs.create(createOpts);

        sendResponse({ pdfUrl, jobTitle, company });
      })
      .catch((err) => {
        console.error("Failed to generate tailored resume:", err);
        sendResponse({ error: String(err) });
      });
    return true;
  }
  return false;
});