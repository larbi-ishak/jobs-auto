# Job Agent — Automated Job Hunting Platform

A multi-country job scraping agent that runs on a schedule, filters relevant jobs,
scores them using an LLM, deduplicates, and sends a Telegram digest every 6 hours.

## Target Countries & Sources

| Country | Job Sources |
|---|---|
| Germany | arbeitnow.com (free API, visa=true filter), Adzuna API (country=de) |
| Canada | Adzuna API (country=ca) |
| France | Adzuna API (country=fr) |
| Ireland | Adzuna API (country=ie) |

## Architecture

```
job_agent/
├── main.py              # Entry point, APScheduler
├── config.py            # All env vars and constants
├── scrapers/
│   ├── __init__.py
│   ├── base.py          # Base scraper class
│   ├── arbeitnow.py     # Germany arbeitnow API
│   └── adzuna.py        # Adzuna multi-country
├── scorer.py            # LLM scoring via Huawei MaaS
├── storage.py           # SQLite operations
├── notifier.py          # Telegram bot
├── candidate_profile.md # Your CV/profile (read by scorer)
└── requirements.txt
```

## Setup

### 1. Clone & Install

```bash
cd /opt
git clone <repo-url> job_agent
cd job_agent/job_agent

python3 -m venv ../venv
source ../venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp ../.env.example ../.env
nano ../.env
```

Fill in all required values:

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID |
| `ADZUNA_APP_ID` | Adzuna API app ID (register at developer.adzuna.com) |
| `ADZUNA_APP_KEY` | Adzuna API app key |
| `HUAWEI_MAAS_BASE_URL` | Huawei MaaS OpenAI-compatible endpoint URL |
| `HUAWEI_MAAS_API_KEY` | Huawei MaaS API key |
| `HUAWEI_MAAS_MODEL` | Model name (default: glm-4) |

### 3. Edit Your Profile

```bash
nano candidate_profile.md
```

Update `candidate_profile.md` with your actual experience, skills, languages,
target roles, and preferences. This file is read at startup and injected into
the LLM scoring prompt.

### 4. Run Manually

```bash
# One-time immediate run
python main.py --now

# Start scheduled (every 6 hours)
python main.py
```

### 5. Deploy as systemd Service (GCP VM / Ubuntu)

```bash
# Copy service file
sudo cp job_agent.service /etc/systemd/system/

# Create log file
sudo touch /var/log/job_agent.log
sudo chown ubuntu:ubuntu /var/log/job_agent.log

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable job_agent
sudo systemctl start job_agent

# Check status
sudo systemctl status job_agent

# View logs
tail -f /var/log/job_agent.log
```

## Pipeline Flow

1. **Scrape** — Fetch jobs from arbeitnow (Germany) and Adzuna (DE/CA/FR/IE)
2. **Filter** — Match against role keywords, detect visa/English mentions
3. **Store** — Deduplicate by URL (MD5 hash), insert new jobs into SQLite
4. **Score** — Send each new job to the LLM for relevance scoring (1-10)
5. **Notify** — Send Telegram digest of top-scored unnotified jobs (max 15)

## Filtering Rules

- Must match at least one role keyword (in title or description)
- Visa sponsorship mentions flagged as priority
- English-language postings accepted; non-English not filtered if they accept English speakers
- Salary below visa threshold flagged as low priority (not excluded)
- No salary data → included normally, marked "not specified"

## Scoring

Each job is scored 1-10 by the LLM based on:
- Role relevance to candidate profile
- Skill match
- Visa likelihood
- Location fit

Only jobs scoring ≥ 6 are included in the Telegram digest.

## Database

SQLite file: `jobs.db` (created automatically)

Table: `seen_jobs` — stores all seen jobs with scores, visa flags, and notification status.

## License

Private — for personal use only.
