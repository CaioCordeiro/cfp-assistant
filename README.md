AI-Powered "Call for Papers" Assistant
======================================

A WhatsApp chatbot that helps speakers turn ideas into CFP-ready submissions, confirm them, and get a confirmation email.

Stack: Twilio WhatsApp + Python (Flask, LangChain + OpenAI) + Twilio SendGrid + SQLite.

Features
--------
- Turns a free-form idea into a structured title and abstract using OpenAI via LangChain.
- Conversational flow with confirmation and email capture.
- Persists submissions in SQLite; quick `STATUS` lookup.
- Sends a SendGrid confirmation email after submission.
- Accepts PDF/PPTX presentations and extracts text to auto-generate the CFP.

Quick Start
-----------
1) Prereqs
- Python 3.11+
- Twilio account with WhatsApp Sandbox or WhatsApp-enabled number
- OpenAI API key
- SendGrid API key

2) Clone and setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in OPENAI_API_KEY, SENDGRID_API_KEY, FROM_EMAIL, etc.
```

3) Run locally
```bash
# Option A: python entrypoint
python -m app.app

# Option B: flask runner
flask --app app.app run --host 0.0.0.0 --port 5000
```

4) Expose a public URL
- Use ngrok or similar to expose: `https://<public-host>/whatsapp`
```bash
ngrok http 5000
```

5) Configure Twilio WhatsApp webhook
- In the Twilio Console → Messaging → WhatsApp Sandbox (or your WhatsApp number), set “WHEN A MESSAGE COMES IN” webhook to your public URL path `/whatsapp`, e.g.: `https://<public-host>/whatsapp`
- Save.

5.1) (Optional) Delivery Status Callback
- Set the Status Callback URL (for Messaging Service or Phone Number) to: `https://<public-host>/status-callback`
- Twilio will POST delivery updates (`queued`, `sent`, `delivered`, `failed`) with fields like `MessageSid`, `MessageStatus`, `ErrorCode`, `To`, `From`.
- This project logs these events for troubleshooting (no database storage).

6) Try it
- From your WhatsApp, send a message to your Twilio WhatsApp number like: "I want to submit a talk about Kubernetes."
- Bot replies with a proposed Title + Abstract and asks you to reply `YES` or `EDIT`.
- Reply `YES`. Bot asks for your email; provide it. You’ll receive a SendGrid confirmation email.
- Send `STATUS` anytime to see recent submissions.

Environment
-----------
Set these in `.env`:
- `LLM_PROVIDER`: `openai` (default) or `huggingface`
- `OPENAI_API_KEY` (if provider=openai): Your OpenAI API key
- `OPENAI_MODEL` (optional, if provider=openai): Defaults to `gpt-4o-mini`
- `HUGGINGFACE_API_KEY` (if provider=huggingface): Your Hugging Face API token
- `HUGGINGFACE_MODEL` (if provider=huggingface): e.g. `Qwen/Qwen2.5-1.5B-Instruct`
- `SENDGRID_API_KEY`: SendGrid API key
- `FROM_EMAIL`: The sender email for confirmations
- `FROM_NAME` (optional): Sender name (default: `CFP Assistant Bot`)
- `VALIDATE_TWILIO_SIGNATURE` (optional): `true`/`false` (default `false`)
- `TWILIO_AUTH_TOKEN` (required if validating): Twilio auth token
- `TWILIO_ACCOUNT_SID` (recommended for media): Used to auth when downloading inbound media from Twilio
- `PUBLIC_BASE_URL` (optional): If signature validation is enabled and your app sits behind a proxy, set this to your public base URL
- `PORT` (optional): Defaults to `5000`

Security Notes
--------------
- Enable Twilio signature validation by setting `VALIDATE_TWILIO_SIGNATURE=true` and providing `TWILIO_AUTH_TOKEN` once you have a stable public URL.
- SQLite database file (`cfp.db`) is created in the repo root by default; customize with `CFP_DB_PATH` env var if needed.

Project Structure
-----------------
```
app/
	app.py          # Flask app + webhook
	cfp_chain.py    # LangChain chain for CFP formatting
	db.py           # SQLite persistence and state
	emailer.py      # SendGrid email helper
requirements.txt
.env.example
```

Notes & Extensions
------------------
- Media ingestion: The webhook accepts PDF (`application/pdf`) and PPTX (`application/vnd.openxmlformats-officedocument.presentationml.presentation`). Text is extracted (first few pages/slides) and fed to the formatter. Very large decks are truncated to keep responses under Twilio timeouts.
- To use a free/open model via Hugging Face Inference API, set `LLM_PROVIDER=huggingface`, add `HUGGINGFACE_API_KEY`, and choose a small instruct model like `Qwen/Qwen2.5-1.5B-Instruct` for lower latency.
- You can return messages either via TwiML (as implemented) or by using Twilio’s REST API to send outbound messages; TwiML keeps the flow simple for webhooks.
- Add a `/status/:id` endpoint or an admin view to browse submissions.
- Extend the chain to extract tags, difficulty, and target audience.
- Add unit tests around the conversation flow and DB operations.

Docker
------
- Build the image:
```bash
docker build -t cfp-assistant:latest .
```
- Run the container (pass env vars and map port):
```bash
docker run --rm -p 5000:5000 \
	-e OPENAI_API_KEY=$OPENAI_API_KEY \
	-e SENDGRID_API_KEY=$SENDGRID_API_KEY \
	-e FROM_EMAIL=cfp-bot@example.com \
	-e FROM_NAME="CFP Assistant Bot" \
	-e PORT=5000 \
	--name cfp-assistant cfp-assistant:latest
```
- Persist the SQLite DB (optional):
```bash
docker run --rm -p 5000:5000 \
	-e OPENAI_API_KEY=$OPENAI_API_KEY \
	-e CFP_DB_PATH=/data/cfp.db \
	-v $(pwd)/.data:/data \
	--name cfp-assistant cfp-assistant:latest
```
- Expose publicly with ngrok:
```bash
ngrok http 5000
```
- Point Twilio WhatsApp webhook to `https://<ngrok-host>/whatsapp`.

# cfp-assistant