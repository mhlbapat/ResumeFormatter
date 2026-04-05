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

  if (msg && msg.type === "START_BATCH_SEARCH") {
    const url = `https://www.linkedin.com/jobs/search/?keywords=${encodeURIComponent(msg.keyword)}`;
    chrome.tabs.create({ url: url }, (tab) => {
      // Wait for it to load
      const listener = (tabId, changeInfo) => {
        if (tabId === tab.id && changeInfo.status === 'complete') {
          chrome.tabs.onUpdated.removeListener(listener);
          // Wait another couple seconds for react to render
          setTimeout(() => {
            chrome.tabs.sendMessage(tabId, { type: "SCRAPE_N_JOBS", size: msg.size }, (response) => {
              if (chrome.runtime.lastError || !response) {
                console.error("Error communicating with scraper:", chrome.runtime.lastError);
                return;
              }
              const jobs = response.jobs || [];
              console.log("Scraped Jobs:", jobs);
              processBatchJobs(jobs);
            });
          }, 3000);
        }
      };
      chrome.tabs.onUpdated.addListener(listener);
    });
    sendResponse({ status: "started" });
    return true;
  }
  return false;
});

async function processBatchJobs(jobs) {
    for (const job of jobs) {
        if (!job.description || job.description.length < 50) continue;
        
        try {
            const resp = await callBackend(job.description);
            handlePdfDownload(resp);
            
            // Open apply tab
            chrome.tabs.create({ url: job.applyUrl }, (tab) => {
                // Wait for it to load to inject script
                const autofillListener = (tabId, changeInfo) => {
                    if (tabId === tab.id && changeInfo.status === 'complete') {
                        chrome.tabs.onUpdated.removeListener(autofillListener);
                        // Inject autofill
                        chrome.scripting.executeScript({
                            target: { tabId: tabId },
                            files: ["scripts/autofill.js"]
                        });
                    }
                };
                chrome.tabs.onUpdated.addListener(autofillListener);
            });
        } catch(e) {
            console.error("Failed batch step", e);
        }
    }
}

function handlePdfDownload(resp) {
    const pdfUrl = `${API_BASE}${resp.pdf_url}`;
    const jobTitle = (resp.job && resp.job.title) || "";
    const company = (resp.job && resp.job.company) || "";
    const candidateName = resp.candidate_name || "Candidate";
    const baseNameParts = [candidateName.replace(/\s+/g,"_"), company.replace(/\s+/g,"_"), jobTitle.replace(/\s+/g,"_")].filter(Boolean);
    const filename = `${baseNameParts.join("_") || "resume"}.pdf`;

    chrome.downloads.download({ url: pdfUrl, filename, saveAs: false }, () => {});
}