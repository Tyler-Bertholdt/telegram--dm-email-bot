import re

class EmailFilterEngine:
    # Security & Automated filters
    OTP_KEYWORDS = [
        r"\botp\b", r"\bverification code\b", r"\bone-time password\b",
        r"\bsecurity code\b", r"\b2fa\b", r"\bpasscode\b", r"\bconfirm your email\b"
    ]
    
    IGNORED_SENDERS = [
        "mailer-daemon@", "postmaster@"
    ]

    @classmethod
    def is_otp_or_security_code(cls, subject: str, snippet: str) -> bool:
        """Returns True if the email is an OTP code."""
        text = f"{subject} {snippet}".lower()
        return any(re.search(pattern, text) for pattern in cls.OTP_KEYWORDS)

    @classmethod
    def is_ignored_sender(cls, sender: str) -> bool:
        """Returns True if email comes from a system mailer daemon."""
        sender_lower = sender.lower()
        return any(ignored in sender_lower for ignored in cls.IGNORED_SENDERS)

    @classmethod
    def should_process_email(cls, sender: str, subject: str, snippet: str) -> bool:
        """Determines if email should trigger a push notification summary."""
        if cls.is_ignored_sender(sender):
            return False
        return True