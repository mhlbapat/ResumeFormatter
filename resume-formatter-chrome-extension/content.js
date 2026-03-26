// Content script for JobApplicationAgent Chrome extension.
// Responsible for returning the user's currently selected text.

function getSelectedJobText() {
  const sel = window.getSelection();
  if (!sel) return "";
  return sel.toString().trim();
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "GET_SELECTED_JOB_TEXT") {
    sendResponse({ text: getSelectedJobText() });
    return true;
  }
  return false;
});

