from dataclasses import dataclass, field
from typing import List


@dataclass
class AttachmentMeta:
    filename: str
    mime_type: str


@dataclass
class MailMessage:
    message_id: str
    thread_id: str
    sender: str
    subject: str
    body: str
    attachments: List[AttachmentMeta] = field(default_factory=list)
