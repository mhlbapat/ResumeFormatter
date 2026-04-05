// LinkedIn job scraper script

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.type === "SCRAPE_N_JOBS") {
    const batchSize = request.size;
    let scrapedJobs = [];
    
    // Attempt to grab job cards
    const jobCards = document.querySelectorAll("li.jobs-search-results__list-item");
    if (jobCards.length === 0) {
      sendResponse({ error: "No job cards found on the page or page still loading." });
      return;
    }

    async function processJobs() {
      for (let i = 0; i < Math.min(batchSize, jobCards.length); i++) {
        const card = jobCards[i];
        card.scrollIntoView();
        card.click();
        
        // Wait for the detail panel to load
        await new Promise(res => setTimeout(res, 2000));
        
        const titleEl = document.querySelector(".job-details-jobs-unified-top-card__job-title");
        const companyEl = document.querySelector(".job-details-jobs-unified-top-card__company-name");
        // For easy apply or external apply
        const applyBtn = document.querySelector(".jobs-apply-button--top-card button") || document.querySelector(".jobs-apply-button");
        const descriptionEl = document.querySelector(".jobs-description__container");
        
        let jd = "";
        if (descriptionEl) {
          jd = descriptionEl.innerText;
        }

        let applyLink = window.location.href; // Fallback to current URL
        if (applyBtn) {
            // Some "Apply Externally" buttons are native links instead of react buttons
            // But if it's Easy Apply, we just use window.location.href
            let externalLink = document.querySelector("a.jobs-apply-button");
            if(externalLink && externalLink.href) applyLink = externalLink.href;
        }
        
        scrapedJobs.push({
          title: titleEl ? titleEl.innerText.trim() : "Unknown Title",
          company: companyEl ? companyEl.innerText.trim() : "Unknown Company",
          description: jd,
          applyUrl: applyLink
        });
      }
      sendResponse({ jobs: scrapedJobs });
    }
    
    processJobs();
    return true; // Keep message channel open for async response
  }
});
