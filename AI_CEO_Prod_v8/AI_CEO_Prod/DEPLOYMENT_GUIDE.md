# Deployment Guide

## Ubuntu / Debian
1. Install Python 3.11+, Docker, Tesseract, and nginx.
2. Copy the project to `/opt/AI_CEO_Prod`.
3. Create a virtualenv and install `requirements.txt`.
4. Run `playwright install chromium`.
5. Copy `ai-ceo.service` to `/etc/systemd/system/` and enable it.
6. Copy `deploy_nginx.conf` into nginx sites-enabled and add TLS.
7. Configure environment variables or dashboard settings.
8. Open firewall for 80/443 only.

## Windows worker
1. Install Python, Docker Desktop, Chrome/Edge, and Tesseract.
2. Run the web app or connect to the cloud host.
3. Register the desktop device in the dashboard.
4. Set `AI_CEO_SERVER`, `AI_CEO_WORKER_TOKEN`, and `AI_CEO_DEVICE_ID`.
5. Run `workers_desktop_agent.py` in the background.
6. Optional: run `workers_whatsapp_monitor.py` after logging into WhatsApp Web.
7. Enable BIOS Wake-on-LAN and router relay if remote wake is required.

## Android
1. Open `android_app` in Android Studio.
2. Change the WebView URL from `10.0.2.2:8000` to your HTTPS host.
3. Build and install the APK.
4. Sign in and allow microphone permissions.

## Production security
- Put the app behind HTTPS.
- Restrict allowed origins.
- Rotate secrets regularly.
- Use dashboard-stored encrypted secrets.
- Back up `instance/`, `captures/`, and the database.
