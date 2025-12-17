import os
import re
import logging
from urllib.parse import urljoin

from dotenv import load_dotenv
from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse
from twilio.request_validator import RequestValidator

from .db import (
    init_db,
    upsert_conversation,
    get_conversation,
    create_submission_draft,
    get_submission,
    delete_submission,
    update_submission_email_and_submit,
    list_submissions_for_user,
)
from .cfp_chain import format_cfp
from .emailer import send_confirmation_email
from .media_extractor import extract_media_text, SUPPORTED_CONTENT_TYPES


load_dotenv()

app = Flask(__name__)
app.logger.setLevel(logging.DEBUG)


EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_number(twilio_from: str) -> str:
    # From value looks like 'whatsapp:+15551234567' or '+15551234567'
    return twilio_from.replace("whatsapp:", "").strip()


def _twilio_signature_valid() -> bool:
    if os.environ.get("VALIDATE_TWILIO_SIGNATURE", "false").lower() != "true":
        return True
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    if not token:
        return True
    validator = RequestValidator(token)
    signature = request.headers.get("X-Twilio-Signature", "")
    # Use request.url if PUBLIC_BASE_URL not set; otherwise rebuild absolute
    public_base = os.environ.get("PUBLIC_BASE_URL")
    full_url = (
        request.url
        if not public_base
        else urljoin(public_base.rstrip("/"), request.path)
    )
    return bool(validator.validate(full_url, request.form, signature))


# Initialize database once at startup (Flask 3 removed before_first_request)
init_db()


def _help_text() -> str:
    return (
        "Hi! I can help with CFPs.\n"
        "- Send your talk idea to get a title + abstract.\n"
        "- Reply YES to submit, or EDIT to revise.\n"
        "- Send STATUS to see your recent submissions."
    )


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}


def _twiml_response(resp: MessagingResponse) -> Response:
    logging.debug("Twilio Response: %s", str(resp))
    return Response(str(resp), status=200, content_type="text/xml")


@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    if not _twilio_signature_valid():
        return Response("Invalid signature", status=403)

    from_number = _normalize_number(request.values.get("From", ""))
    body = (request.values.get("Body") or "").strip()
    lower = body.lower()
    num_media = int(request.values.get("NumMedia", "0") or "0")

    resp = MessagingResponse()

    if not from_number:
        resp.message("Missing sender number.")
        return Response(str(resp), mimetype="application/xml")

    # Quick commands handled anytime
    if lower in {"help", "menu"}:
        resp.message(_help_text())
        return _twiml_response(resp)

    if "status" in lower:
        rows = list_submissions_for_user(from_number, limit=5)
        if not rows:
            resp.message("No submissions found yet. Send your idea to begin.")
            return _twiml_response(resp)
        lines = ["Your recent submissions:"]
        for r in rows:
            title = (r["title"] or "(untitled)")[:80]
            lines.append(f"#{r['id']}: {title} — {r['status']}")
        resp.message("\n".join(lines))
        return _twiml_response(resp)

    # Instant test path to validate Twilio delivery
    if lower in {"ping", "test"}:
        resp.message("pong")
        return _twiml_response(resp)

    # If media present, try to extract text and treat as idea
    if num_media > 0:
        media_url = request.values.get("MediaUrl0")
        media_ct = request.values.get("MediaContentType0", "")
        if not media_url or not media_ct:
            resp.message(
                "I received a file but couldn't read its metadata. Please try again."
            )
            return _twiml_response(resp)
        if media_ct not in SUPPORTED_CONTENT_TYPES:
            resp.message(
                "Unsupported file type. Please send a PDF or PPTX presentation."
            )
            return _twiml_response(resp)
        try:
            extracted = extract_media_text(media_url, media_ct)
        except Exception as e:
            app.logger.exception("Failed to fetch/extract media: %s", e)
            resp.message(
                "I couldn't read that file. Please confirm it's a PDF or PPTX and try again."
            )
            return _twiml_response(resp)
        if not extracted or len(extracted.strip()) < 50:
            resp.message(
                "I couldn't extract enough text from the file. Please send a clearer PDF/PPTX or include some notes in the message."
            )
            return _twiml_response(resp)

        # Proceed as if user sent an idea text
        body = extracted
        lower = body.lower()

    convo = get_conversation(from_number)
    state = convo["state"] if convo else "idle"
    submission_id = convo["submission_id"] if convo else None

    if state == "idle":
        # Treat any message as an idea to format
        if not os.environ.get("OPENAI_API_KEY"):
            app.logger.error("Missing OPENAI_API_KEY; cannot format CFP.")
            resp.message(
                "Service not configured: OpenAI API key is missing. Please set OPENAI_API_KEY on the server."
            )
            return _twiml_response(resp)
        try:
            cfp = format_cfp(body)
        except Exception as e:
            app.logger.exception("Error while formatting CFP: %s", e)
            resp.message(
                "Sorry, I couldn't format that right now. Please try again in a moment."
            )
            return _twiml_response(resp)

        # Log model response (title + abstract length, avoid full content spam)
        try:
            app.logger.info(
                "CFP generated: from=%s title=%s abstract_len=%d",
                from_number,
                cfp.title[:120].replace("\n", " "),
                len(cfp.abstract or ""),
            )
        except Exception:
            pass

        submission_id = create_submission_draft(
            from_number,
            cfp.title,
            cfp.abstract,
            cfp.private_message,
            cfp.main_language,
            cfp.talk_type,
            cfp.intended_audience,
            cfp.estimated_duration,
            cfp.live_coding,
            cfp.special_requirements,
        )
        upsert_conversation(from_number, "awaiting_confirm", submission_id)

        # Build a richer preview including key CFP fields
        live_coding_str = (
            "Yes"
            if str(getattr(cfp, "live_coding", "")).strip().lower()
            in {"yes", "true", "1"}
            else str(getattr(cfp, "live_coding", "No") or "No")
        )
        reply_lines = [
            "Here’s a formatted proposal:",
            "",
            f"Title: {cfp.title}",
            "",
            "Abstract:",
            f"{cfp.abstract}",
            "",
            "Organizer Notes:",
            f"- Private message:\n {getattr(cfp, 'private_message', '') or 'N/A'}",
            f"- Language: {getattr(cfp, 'main_language', '') or 'N/A'}",
            f"- Talk type: {getattr(cfp, 'talk_type', '') or 'N/A'}",
            f"- Audience: {getattr(cfp, 'intended_audience', '') or 'N/A'}",
            f"- Duration: {getattr(cfp, 'estimated_duration', '') or 'N/A'}",
            f"- Live coding: {live_coding_str}",
            f"- Special requirements: {getattr(cfp, 'special_requirements', '') or 'None'}",
            "",
            "Reply YES to submit.",
            "Reply EDIT to revise with more details.",
            "Send STATUS to view your recent submissions.",
        ]
        reply = "\n".join(reply_lines)
        resp.message(reply)
        return _twiml_response(resp)

    if state == "awaiting_confirm" and submission_id:
        if lower in {"yes", "y", "submit", "ok", "okay", "confirm"}:
            upsert_conversation(from_number, "awaiting_email", submission_id)
            resp.message("Great! What email should I use for confirmation?")
            return _twiml_response(resp)
        if lower in {"no", "n", "cancel", "stop"}:
            delete_submission(int(submission_id))
            upsert_conversation(from_number, "idle", None)
            resp.message("No problem — submission canceled. Send a new idea anytime.")
            return _twiml_response(resp)
        if lower.startswith("edit"):
            upsert_conversation(from_number, "idle", None)
            resp.message("Sure — send your revised idea and I’ll reformat it.")
            return _twiml_response(resp)

        resp.message("Ongoing CFP, please send YES, EDIT or STATUS.")
        return _twiml_response(resp)

    if state == "awaiting_email" and submission_id:
        if not EMAIL_REGEX.match(body):
            resp.message(
                "That doesn't look like an email. Please try again (e.g., name@example.com)."
            )
            return _twiml_response(resp)

        update_submission_email_and_submit(int(submission_id), body)
        sub = get_submission(int(submission_id))

        try:
            send_confirmation_email(
                body, sub["title"], sub["abstract"], int(submission_id)
            )
        except Exception:
            # Best effort email; continue without failing
            pass

        upsert_conversation(from_number, "idle", None)
        resp.message(
            f"Submitted! Your ID is #{submission_id}. A confirmation email was sent to {body}."
        )
        return _twiml_response(resp)

    # Fallback: reset and start over
    upsert_conversation(from_number, "idle", None)
    resp.message(
        "Let’s start fresh — send your talk idea and I’ll format it into a title and abstract."
    )
    return _twiml_response(resp)


@app.route("/status-callback", methods=["POST"])
def status_callback():
    # Optional signature validation
    if not _twilio_signature_valid():
        # Don't block status callbacks in dev unless explicitly enabled
        pass

    # Twilio sends form-encoded fields
    sid = request.form.get("MessageSid") or request.form.get("SmsSid") or ""
    status = (
        request.form.get("MessageStatus") or request.form.get("SmsStatus") or "unknown"
    )
    error_code = request.form.get("ErrorCode")
    to_number = request.form.get("To")
    from_number = request.form.get("From")

    app.logger.info(
        "Twilio status callback: sid=%s status=%s error=%s to=%s from=%s",
        sid,
        status,
        error_code,
        to_number,
        from_number,
    )

    # Twilio expects a 200 with empty body
    return ("", 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
