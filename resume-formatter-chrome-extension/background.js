// Background/service worker for ResumeFormatter Chrome extension.
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

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.type === "GENERATE_RESUME_FROM_TEXT") {
    // Normal single mode
    const description = String(msg.description || "").trim();
    if (!description) { sendResponse({ error: "Job description cannot be empty." }); return true; }
    callBackend(description)
      .then((resp) => {
        handlePdfDownload(resp);
        const pdfUrl = `${API_BASE}${resp.pdf_url}`;
        chrome.tabs.create({ url: pdfUrl });
        sendResponse({ pdfUrl, jobTitle: resp.job?.title, company: resp.job?.company });
      }).catch(err => sendResponse({ error: String(err) }));
    return true;
  }

  return false;
});

function handlePdfDownload(resp) {
    const pdfUrl = `${API_BASE}${resp.pdf_url}`;
    const jobTitle = (resp.job && resp.job.title) || "";
    const company = (resp.job && resp.job.company) || "";
    const candidateName = resp.candidate_name || "Candidate";
    const baseNameParts = [candidateName.replace(/\s+/g,"_"), company.replace(/\s+/g,"_"), jobTitle.replace(/\s+/g,"_")].filter(Boolean);
    const filename = `${baseNameParts.join("_") || "resume"}.pdf`;

    chrome.downloads.download({ url: pdfUrl, filename, saveAs: false }, () => {});
}