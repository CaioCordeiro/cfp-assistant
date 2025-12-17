import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content


def send_confirmation_email(to_email: str, title: str, abstract: str, submission_id: int) -> None:
    api_key = os.environ.get("SENDGRID_API_KEY")
    from_email = os.environ.get("FROM_EMAIL")
    from_name = os.environ.get("FROM_NAME", "CFP Assistant")

    if not api_key or not from_email:
        # Fail silently but do not crash the webhook
        return

    sg = SendGridAPIClient(api_key)
    subject = f"CFP Submission Confirmation #{submission_id}"
    body = (
        f"Thanks for your submission!\n\n"
        f"Submission ID: {submission_id}\n\n"
        f"Title:\n{title}\n\n"
        f"Abstract:\n{abstract}\n\n"
        f"We’ll keep you posted on next steps."
    )

    message = Mail(
        from_email=Email(from_email, from_name),
        to_emails=To(to_email),
        subject=subject,
        plain_text_content=Content("text/plain", body),
    )

    sg.send(message)
