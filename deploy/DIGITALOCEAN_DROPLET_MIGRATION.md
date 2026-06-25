# DigitalOcean Droplet Migration Guide

This guide moves the project from the current droplet to a new DigitalOcean droplet.

Use this when:
- the current server is too slow
- you want to move from Shared CPU to General Purpose
- you want to move to another region such as Bangalore

This guide assumes:
- old server project path: `/opt/youtube-automation/football-pulse`
- old server login user: `root`
- app runs with Docker Compose
- database is SQLite

---

## 1. Collect Required Information

Before starting, keep these ready:

- old droplet IP
- new droplet IP
- SSH key already working from your PC
- GitHub repo URL
- current `.env`
- any extra non-git credential files you use

---

## 2. Stop the Old App Cleanly

SSH into the old server:

```bash
ssh root@OLD_SERVER_IP
```

Go to the project:

```bash
cd /opt/youtube-automation/football-pulse
```

Stop the running app:

```bash
docker compose stop autonews
```

Check it stopped:

```bash
docker ps
```

---

## 3. Back Up the Old Server

Create a backup folder:

```bash
mkdir -p /root/backups/football-pulse
```

Copy the main runtime files:

```bash
cp /opt/youtube-automation/football-pulse/.env /root/backups/football-pulse/.env
cp /opt/youtube-automation/football-pulse/database/articles.db /root/backups/football-pulse/articles.db
```

Archive the whole project:

```bash
tar -czf /root/backups/football-pulse/project-files.tar.gz -C /opt/youtube-automation football-pulse
```

Optional: if you use any extra credential files that are not in git, copy them too:

```bash
cp /path/to/extra-file.json /root/backups/football-pulse/
```

List backup files:

```bash
ls -lah /root/backups/football-pulse
```

---

## 4. Restart the Old Server App

Bring the old app back up so the service stays live during migration:

```bash
cd /opt/youtube-automation/football-pulse
docker compose up -d
docker ps
```

---

## 5. Download Backups to Your PC

Run these from PowerShell on your PC:

```powershell
scp root@OLD_SERVER_IP:/root/backups/football-pulse/.env C:\Users\sufya\Desktop\
scp root@OLD_SERVER_IP:/root/backups/football-pulse/articles.db C:\Users\sufya\Desktop\
scp root@OLD_SERVER_IP:/root/backups/football-pulse/project-files.tar.gz C:\Users\sufya\Desktop\
```

If you backed up extra credential files, copy those too.

---

## 6. Create the New Droplet

In DigitalOcean:

1. Click `Create`
2. Select `Droplets`
3. Choose region `Bangalore`
4. Choose `General Purpose`
5. Choose `2 vCPU / 8 GB RAM`
6. Select Ubuntu
7. Use your existing SSH key
8. Name the server, for example `youtube-automation-prod-blr`
9. Create droplet

After creation, note the new IP address.

---

## 7. SSH Into the New Droplet

```bash
ssh root@NEW_SERVER_IP
```

Optional basic checks:

```bash
pwd
ls
```

---

## 8. Install Docker on the New Droplet

Install Docker if not already installed:

```bash
apt update
apt install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
. /etc/os-release && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Verify:

```bash
docker --version
docker compose version
```

---

## 9. Install Host Dependencies

If you need livestream support on the new server, install host packages too:

```bash
apt install -y ffmpeg xvfb
```

If Chrome is needed for livestream, install it the same way you did on the old droplet.

Check:

```bash
which ffmpeg
which Xvfb
which google-chrome
```

---

## 10. Clone the Project on the New Droplet

```bash
mkdir -p /opt/youtube-automation
cd /opt/youtube-automation
git clone https://github.com/Sufyan-Ali1/football-pulse.git
cd football-pulse
```

Check:

```bash
pwd
ls
```

---

## 11. Upload Backups to the New Droplet

Run these from PowerShell on your PC:

```powershell
scp C:\Users\sufya\Desktop\.env root@NEW_SERVER_IP:/opt/youtube-automation/football-pulse/.env
scp C:\Users\sufya\Desktop\articles.db root@NEW_SERVER_IP:/opt/youtube-automation/football-pulse/database/articles.db
scp C:\Users\sufya\Desktop\project-files.tar.gz root@NEW_SERVER_IP:/root/project-files.tar.gz
```

If you have extra credential files, upload them too.

---

## 12. Restore Runtime Folders and Permissions

On the new droplet:

```bash
cd /opt/youtube-automation/football-pulse
mkdir -p database temp logs config/fonts
chmod -R 777 database temp logs
```

Check the DB file exists:

```bash
ls -lah database
```

---

## 13. Fix Server-Specific `.env` Values

Open the server `.env`:

```bash
nano /opt/youtube-automation/football-pulse/.env
```

Update Linux-specific values as needed:

```env
LIVESTREAM_CHROMIUM_BIN=/usr/bin/google-chrome
LIVESTREAM_FFMPEG_BIN=/usr/bin/ffmpeg
LIVESTREAM_XVFB_BIN=/usr/bin/Xvfb
THUMBNAIL_ENABLED=false
```

Important:
- remove any old Windows-only path like `C:\...`
- especially remove or fix `GOOGLE_APPLICATION_CREDENTIALS` if it points to a Windows path

Check important env keys without printing secret values fully:

```bash
grep -E "GROQ_API_KEY|GOOGLE_CLIENT_ID|GOOGLE_CLIENT_SECRET|YOUTUBE_REFRESH_TOKEN|GDRIVE_REFRESH_TOKEN|GOOGLE_DRIVE_FOLDER_ID|THUMBNAIL_ENABLED|GOOGLE_APPLICATION_CREDENTIALS|LIVESTREAM_" .env
```

---

## 14. Upload Missing Font Files if Needed

If your video text was rendering incorrectly before, upload the font files from your PC:

```powershell
scp C:\Windows\Fonts\impact.ttf root@NEW_SERVER_IP:/opt/youtube-automation/football-pulse/config/fonts/
scp C:\Windows\Fonts\arial.ttf root@NEW_SERVER_IP:/opt/youtube-automation/football-pulse/config/fonts/
scp C:\Windows\Fonts\arialbd.ttf root@NEW_SERVER_IP:/opt/youtube-automation/football-pulse/config/fonts/
```

Then verify on the server:

```bash
ls -lah /opt/youtube-automation/football-pulse/config/fonts
```

---

## 15. Start the App on the New Droplet

```bash
cd /opt/youtube-automation/football-pulse
docker compose up -d --build
docker ps
docker compose logs --tail=200
```

Wait until the container shows `healthy`.

---

## 16. Validate the Database on the New Droplet

Count saved records:

```bash
cd /opt/youtube-automation/football-pulse
docker compose exec autonews python -c "import sqlite3; from core.database import _DB_PATH; c=sqlite3.connect(_DB_PATH); print('articles=', c.execute('SELECT COUNT(*) FROM articles').fetchone()[0]); print('daily_videos=', c.execute('SELECT COUNT(*) FROM daily_videos').fetchone()[0]); print('video_clips=', c.execute('SELECT COUNT(*) FROM video_clips').fetchone()[0]); c.close()"
```

Check recent daily run status:

```bash
docker compose exec autonews python -c "import sqlite3; from core.database import _DB_PATH; c=sqlite3.connect(_DB_PATH); print(c.execute('SELECT video_date, status, video_path, error FROM daily_videos ORDER BY rowid DESC LIMIT 5').fetchall()); c.close()"
```

---

## 17. Test the Pipeline Manually

Run one collector cycle:

```bash
cd /opt/youtube-automation/football-pulse
docker compose exec autonews python main.py --once
```

Run one daily video manually:

```bash
docker compose exec autonews python -u -c "from pipeline.daily_runner import run_daily_video; run_daily_video()" | tee /root/manual_daily_run.log
```

Read the manual run log:

```bash
cat /root/manual_daily_run.log
```

---

## 18. Update GitHub Auto-Deploy

In GitHub repository secrets, update:

- `DIGITALOCEAN_HOST` -> new Bangalore droplet IP

If the SSH key is unchanged, `DIGITALOCEAN_SSH_KEY` stays the same.

Then test by pushing a small commit to `main`.

---

## 19. Stop the Old Droplet App After Cutover

Once the new server is confirmed working, stop the old server app:

```bash
ssh root@OLD_SERVER_IP
cd /opt/youtube-automation/football-pulse
docker compose down
docker ps
```

This prevents duplicate scheduled uploads.

---

## 20. Keep the Old Droplet Briefly as Rollback

Do not destroy the old droplet immediately.

Keep it for a short safety window until all of these are confirmed:

- collector works
- manual daily video works
- YouTube upload works
- clip downloads from Drive work
- GitHub auto-deploy works
- text/fonts render correctly

---

## 21. Destroy the Old Droplet

After validation, destroy the old droplet from the DigitalOcean control panel.

Only do this after you are sure the new droplet is fully stable.

---

## 22. Quick Troubleshooting

If SQLite fails to open:

```bash
chmod -R 777 /opt/youtube-automation/football-pulse/database /opt/youtube-automation/football-pulse/temp /opt/youtube-automation/football-pulse/logs
docker compose up -d --build
```

If thumbnail fails with a Windows path error:

- remove the Windows `GOOGLE_APPLICATION_CREDENTIALS` path from `.env`
- or set `THUMBNAIL_ENABLED=false`
- rebuild container

If text looks wrong:

- upload `impact.ttf`, `arial.ttf`, `arialbd.ttf` into `config/fonts`
- rebuild container

If upload fails:

check:

```bash
docker compose exec autonews python -c "import sqlite3; from core.database import _DB_PATH; c=sqlite3.connect(_DB_PATH); print(c.execute('SELECT video_date, status, video_path, error FROM daily_videos ORDER BY rowid DESC LIMIT 5').fetchall()); c.close()"
```

