# Football Credo Hub – Tech Stack & What We Need From You

**Project:** Football AutoNews Engine  
**Prepared by:** Sufyan Ali

---

## Tech Stack Decision

After evaluating all options, I have finalized **Python** as the core technology for this project (not n8n or any no-code tool). Here is why:

- Python gives full control over video editing, cinematic transitions, and audio processing — things no-code tools cannot handle
- The 24/7 livestream requires a persistent FFmpeg process that only Python can run
- Scales easily — any new feature or API can be added with a single library install
- No workflow timeouts — the pipeline can run as long as needed per video (some AI steps take 20–30 minutes)
- **Hosting:** Railway.app at $5/month — covers the full pipeline running 24/7

---

## Finalized API Stack

Below is every service being used, why it was chosen, and the approximate monthly cost.

---

### Script Generation — Groq (Free)

| | |
|---|---|
| **Service** | Groq |
| **Model** | Llama 3.1 70B (via Groq API) |
| **Cost** | **Free tier** |
| **Why** | Groq's free tier provides more than enough capacity for this pipeline. It runs Llama 3.1 70B which is comparable to GPT-4 for news script writing. Choosing this over OpenAI saves ~$30–50/month in API costs. |
| **What you need to provide** | Create a free account at groq.com → go to API Keys → create a key → send to me |

---

### English Voiceover — Google Text-to-Speech (Free)

| | |
|---|---|
| **Service** | Google Cloud Text-to-Speech |
| **Cost** | **Free** (up to 1 million characters/month) |
| **Why** | High quality, free, and more than enough for daily video production. No paid plan needed. |
| **What you need to provide** | Nothing extra — this uses the same Google Cloud project as YouTube API |

---

### Yoruba Voiceover — ElevenLabs (Module 3 & 4 only)

| | |
|---|---|
| **Service** | ElevenLabs |
| **Plan** | Starter |
| **Cost** | ~$5/month |
| **Why** | ElevenLabs is the **only** major TTS provider that supports Yoruba language. No alternative exists. This is used only for Yoruba videos (Module 3 & 4), not for English videos — keeping cost low. |
| **What you need to provide** | Sign up at elevenlabs.io (Starter plan) → API Key + Yoruba Voice ID |

---

### Thumbnail Generation — Python (Pillow library)

| | |
|---|---|
| **Service** | Python Pillow (built-in library) |
| **Cost** | **Free** |
| **Why** | Generates branded thumbnails programmatically. No external API needed. We provide the logo, colours and headline — Pillow builds the thumbnail automatically. Removes the cost of Canva API entirely. |
| **What you need to provide** | Channel logo (PNG, transparent background) + brand colours (hex codes) |

---

### Twitter / X News Monitoring — Apify Twitter Scraper

| | |
|---|---|
| **Service** | Apify (Twitter scraper actor) |
| **Cost** | ~$20/month |
| **Why** | The official Twitter API costs **$100/month minimum** (Basic plan) just to read tweets. Apify scrapes the same data for ~$20/month. Saves $80/month with no loss of functionality. |
| **Important limitation** | Apify has a **~20–25 minute delay** compared to real-time. Breaking news will appear in the pipeline 20–25 minutes after the journalist tweets. RSS feeds (Sky Sports, BBC Sport, etc.) have no delay and cover most breaking news anyway. If real-time Twitter is critical, we can upgrade to the official API at $100/month later. |
| **What you need to provide** | Sign up at apify.com → API Key |

---

### Other News Sources — RSS Feeds (Free)

The pipeline monitors these feeds every 5 minutes at no cost:

- Sky Sports Football
- BBC Sport Football
- Goal.com
- ESPN FC
- TalkSport
- Google Alerts (you set up alerts for keywords like "transfer", "signing", etc. — Google provides an RSS URL for each)

---

### YouTube Publishing — YouTube Data API v3

| | |
|---|---|
| **Service** | YouTube Data API v3 (Google) |
| **Cost** | **Free** |
| **What you need to provide** | Create a Google Cloud project → enable YouTube Data API v3 → download OAuth2 credentials JSON → send to me. Full steps below. |

#### Steps to get YouTube API credentials
1. Go to console.cloud.google.com
2. Create a new project (name it "Football Lacuna HQ")
3. Search for and enable **YouTube Data API v3**
4. Go to **APIs & Services → Credentials**
5. Click **Create Credentials → OAuth 2.0 Client ID**
6. Application type: **Desktop app**
7. Download the JSON file and send it to me

---

### File Storage — Google Drive

| | |
|---|---|
| **Service** | Google Drive |
| **Cost** | Free (uses existing Google account) |
| **What you need to provide** | Create a folder in Google Drive → share it with `sufyanjatts199@gmail.com` as Editor → send me the folder ID (visible in the URL) |

---

### Additional Tools — Required Later

We will also need the following once the core pipeline is tested and ready. Full setup details will be shared separately:

- **HeyGen** — AI presenter video generation
- **Creatomate** — video branding overlays and news ticker
- **Buffer** — automatic social media posting (TikTok, Instagram, X, YouTube Shorts)
- **Railway.app** — cloud hosting for the pipeline ($5/month). This is where the entire system will run 24/7. Account setup instructions will be provided when we move to deployment.

---

## Cost Summary

| Service | Monthly Cost |
|---|---|
| Hosting (Railway.app) | $5 |
| Groq (script generation) | Free |
| Google TTS (English voiceover) | Free |
| ElevenLabs (Yoruba only) | $5 |
| HeyGen (AI presenter) | ~$29 |
| Creatomate (video branding) | ~$29 |
| Apify (Twitter scraping) | ~$20 |
| Thumbnail generation (Pillow) | Free |
| YouTube API | Free |
| RSS feeds | Free |
| **Total** | **~$88/month** |

---

## What You Need to Send Me Now

### Required Before Testing Starts
- [ ] YouTube channel access — add `sufyanjatts199@gmail.com` as **Manager** in YouTube Studio → Settings → Permissions
- [ ] YouTube API credentials JSON — follow the steps in the YouTube section above
- [ ] YouTube Channel ID — YouTube Studio → Settings → Channel → Advanced settings
- [ ] Groq API key — groq.com → API Keys → Create key
- [ ] Apify API key — apify.com → Settings → Integrations → API token
- [ ] Google Drive folder ID — create a folder and share with `sufyanjatts199@gmail.com`
- [ ] Channel logo (PNG, transparent background, min 500×500px)

### Required Later (Phase 3 — Yoruba Videos)
- [ ] ElevenLabs API key + Yoruba Voice ID
- [ ] Yoruba reviewer contact (to check AI-generated Yoruba scripts)

### Required Before Go-Live (Livestream)
- [ ] YouTube Stream Key — YouTube Studio → Go Live → Stream key

---

## Question — Daily Upload vs Sunday Approval

The system supports two publishing flows:

1. **Direct Upload** — video is generated and published to YouTube automatically as soon as news is detected. No review, no delay.
2. **Sunday Approval** — video is queued and held. Every Sunday you receive a list of pending videos to review. Only approved ones get published.

**Please confirm:**
- Which types of videos do you want to go through Sunday approval before publishing?
- Which types of videos are you happy to have upload automatically without review?

For example: breaking news and transfers might go direct, while analysis or opinion videos might need your approval first. Let us know what works best for you.

---

*Prepared by Sufyan Ali*
