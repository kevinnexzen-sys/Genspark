# AI CEO Production Checklist

## Implemented in code
- CEO heartbeat loop
- Offline/online hybrid provider routing
- Multi-provider switching
- Watch-to-learn ingestion
- Search-to-skill conversion
- Automation suggestions
- Self-improving critic loop
- Persistent skills with version history
- Unified learning graph for phone + desktop events
- Android standalone wrapper project
- Mobile voice speaking path in UI
- Desktop listen-only voice behavior in UI/worker
- Remote PC wake/control paths
- Smart plug fallback path
- Side-by-side preview
- Project knowledge/instructions views
- WhatsApp webhook command path
- Google Sheets / Email / Calendar integration tests
- Dashboard-first settings
- Dynamic subagents
- Queued tasks waiting for workers
- Resume after worker online heartbeat
- Wake-on-LAN / cloud relay / smart plug / Intel AMT hook
- Restart / shutdown / online detection / wake retry chain
- Docker deployment assets
- Windows auto-start
- Supabase schema for event mirror

## Manual external prerequisites before any complete production claim
- Supabase project actually provisioned and keys inserted
- Google service account credentials actually created and inserted
- Chrome installed and logged into WhatsApp Web if browser monitoring is required
- BIOS Wake-on-LAN enabled on target PC
- Router / relay setup if remote wake beyond LAN is needed
- Smart plug configured if fallback power control is needed
- Cloud host deployed and protected with HTTPS / firewall / backups
- Android APK built and installed on target device
- Tesseract installed on host for OCR
- Docker daemon running if sandbox isolation is expected
