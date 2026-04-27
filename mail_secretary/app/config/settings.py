import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppSettings:
    gcp_project_id: str = os.getenv("GCP_PROJECT_ID", "")
    secret_prefix: str = os.getenv("SECRET_PREFIX", "mail-secretary")
    app_env: str = os.getenv("APP_ENV", "dev")
    poll_max_results: int = int(os.getenv("POLL_MAX_RESULTS", "10"))
    mail_query: str = os.getenv("MAIL_QUERY", "newer_than:1d -in:spam")
    pdf_force_for_code: bool = os.getenv("PDF_FORCE_FOR_CODE", "true").lower() == "true"
