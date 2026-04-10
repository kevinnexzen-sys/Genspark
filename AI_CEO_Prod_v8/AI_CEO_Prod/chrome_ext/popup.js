const log = document.getElementById('log');
const setLog = msg => log.textContent = msg;

document.getElementById('run').onclick = async () => {
  const cmd = document.getElementById('cmd').value.trim();
  if (!cmd) return;
  setLog('Running...');
  try {
    const resp = await fetch('http://127.0.0.1:8000/api/command', {
      method: 'POST',
      credentials: 'include',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({cmd})
    });
    setLog(JSON.stringify(await resp.json(), null, 2));
  } catch (e) {
    setLog(String(e));
  }
};

document.getElementById('cap').onclick = async () => {
  setLog('Capturing...');
  chrome.runtime.sendMessage({type: 'capture'}, res => {
    setLog(JSON.stringify(res, null, 2));
  });
};
