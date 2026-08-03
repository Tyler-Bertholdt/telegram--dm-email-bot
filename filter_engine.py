from config import config

class EmailFilterEngine:
    @classmethod
    def should_process_email(cls, sender: str, subject: str, snippet: str) -> bool:
        """If filtering is toggled OFF, every email is processed."""
        if not config.ENABLE_FILTERING:
            return True
            
        # Optional basic daemon check if filtering is manually toggled ON
        if "mailer-daemon@" in sender.lower() or "postmaster@" in sender.lower():
            return False
        return True