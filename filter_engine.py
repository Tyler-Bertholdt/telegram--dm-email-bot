import re

class EmailFilterEngine:
    # Patterns indicating OTPs or verification codes
    OTP_KEYWORDS = [
        r"\botp\b", r"\bverification code\b", r"\bone-time password\b",
        r"\bsecurity code\b", r"\b2fa\b", r"\bpasscode\b", r"\bconfirm your email\b"
    ]
    
    # Automated senders to ignore
    IGNORED_SENDERS = [
        "no-reply@", "noreply@", "donotreply@", "mailer-daemon@"
    ]

    @classmethod
    def is_otp_or_security_code(cls, subject: str, snippet: str) -> bool:
        """Returns True if the email appears to be an OTP or security verification."""
        text = f"{subject} {snippet}".lower()
        for pattern in cls.OTP_KEYWORDS:
            if re.search(pattern, text):
                return True
        return False

    @classmethod
    def is_ignored_sender(cls, sender: str) -> bool:
        """Returns True if email comes from a blacklisted automated address."""
        sender_lower = sender.lower()
        return any(ignored in sender_lower for ignored in cls.IGNORED_SENDERS)

    @classmethod
    def should_process_email(cls, sender: str, subject: str, snippet: str) -> bool:
        """Master check to decide if email should be processed and sent to Telegram."""
        if cls.is_ignored_sender(sender):
            return False
        if cls.is_otp_or_security_code(subject, snippet):
            return False
        return True