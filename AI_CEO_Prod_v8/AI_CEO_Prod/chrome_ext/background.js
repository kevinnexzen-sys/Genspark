chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'capture') {
    chrome.tabs.captureVisibleTab(null, {format: 'png'}, dataUrl => {
      fetch('http://127.0.0.1:8000/api/capture', {
        method: 'POST',
        credentials: 'include',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({img: dataUrl, url: sender.tab?.url || ''})
      })
      .then(r => r.json())
      .then(data => sendResponse({ok: true, data}))
      .catch(err => sendResponse({ok: false, error: String(err)}));
    });
    return true;
  }
});
