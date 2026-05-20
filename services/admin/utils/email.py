# admin/utils/email.py

from core.utils.email_service import send_email as send_email_centralized

async def send_email(to_email: str, subject: str, body: str):
    """Send email using centralized email service (SendGrid)"""
    try:
        result = await send_email_centralized(
            to_email=to_email,
            subject=subject,
            body=body,
            is_html=True  # Assuming body is HTML, change to False if plain text
        )
        
        if result:
            print("✅ Email sent successfully.")
        else:
            print("❌ Failed to send email.")
        
        return result
    except Exception as e:
        print("❌ Failed to send email.")
        print(f"Error: {e}")
        return False
