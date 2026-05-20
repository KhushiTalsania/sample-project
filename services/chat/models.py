from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Literal
from datetime import datetime
from enum import Enum


def is_html_content(content: str) -> bool:
    """Check if content contains HTML tags"""
    if not content:
        return False

    # Common HTML tags to detect
    html_tags = [
        "<!DOCTYPE",
        "<html",
        "<head",
        "<body",
        "<p",
        "<div",
        "<span",
        "<h1",
        "<h2",
        "<h3",
        "<h4",
        "<h5",
        "<h6",
        "<b>",
        "<i>",
        "<u>",
        "<strong>",
        "<em>",
        "<br>",
        "<hr>",
        "<a",
        "<img",
        "<ul>",
        "<ol>",
        "<li>",
        "<table>",
        "<tr>",
        "<td>",
        "<th>",
        "<form>",
        "<input>",
        "<button>",
        "<script>",
        "<style>",
        "<sub>",
        "<sup>",
        "<small>",
        "<big>",
        "<pre>",
        "<code>",
        "<blockquote>",
        "<cite>",
    ]

    content_lower = content.lower().strip()
    return any(tag in content_lower for tag in html_tags)


class MessageType(str, Enum):
    TEXT = "text"
    EMOJI = "emoji"
    GIF = "gif"
    SYSTEM = "system"  # For system messages like user joined/left


class ReactionType(str, Enum):
    EMOJI = "emoji"
    GIF = "gif"


class UserRole(str, Enum):
    CAPTAIN = "Captain"
    MODERATOR = "Moderator"
    MEMBER = "Member"


class MembershipStatus(str, Enum):
    TRIAL = "trial"
    PAID = "paid"
    ACTIVE = "active"


class ThreadStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    LOCKED = "locked"


# User Models
class ChatUser(BaseModel):
    user_id: str
    username: str
    full_name: str
    avatar_url: Optional[str] = None
    role: UserRole
    membership_status: MembershipStatus
    is_muted: bool = Field(default=False)
    last_seen: Optional[datetime] = None


class UserMention(BaseModel):
    user_id: str
    username: str
    full_name: str
    position_start: int = Field(description="Start position of mention in message")
    position_end: int = Field(description="End position of mention in message")


# Message Models
class MessageContent(BaseModel):
    text: str
    mentions: List[UserMention] = Field(default=[])
    file_attachments: List[str] = Field(default=[])  # List of file IDs
    is_html: bool = Field(
        default=False, description="Whether the content contains HTML"
    )

    @validator("text")
    def validate_text_length(cls, v):
        # MongoDB BSON document limit is 16MB, but we set a reasonable limit for UX
        # This allows for much longer messages while maintaining good performance
        if len(v) > 50000:  # 50KB - much more reasonable than 2000 chars
            raise ValueError("Message text cannot exceed 50,000 characters")
        return v

    def __init__(self, **data):
        # Auto-detect HTML content
        if "text" in data:
            data["is_html"] = is_html_content(data["text"])
        super().__init__(**data)


class MessageReaction(BaseModel):
    reaction_id: str
    user_id: str
    username: str
    reaction_type: ReactionType
    content: str = Field(description="Emoji unicode or GIF URL")
    created_at: datetime


class PinnedMessage(BaseModel):
    pinned_by: str = Field(description="User ID who pinned the message")
    pinned_by_username: str
    pinned_by_full_name: Optional[str] = None
    pinned_at: datetime
    reason: Optional[str] = None


class ChatMessage(BaseModel):
    message_id: str
    club_id: str
    sender_id: str
    sender_username: str
    sender_full_name: str
    sender_avatar: Optional[str] = None
    sender_role: UserRole
    message_type: MessageType
    content: MessageContent
    reactions: List[MessageReaction] = Field(default=[])
    pinned: Optional[PinnedMessage] = None
    reply_to_message_id: Optional[str] = None
    edited_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


# Request/Response Models
class SendMessageRequest(BaseModel):
    club_id: str
    message_type: MessageType = MessageType.TEXT
    content: str = Field(..., min_length=1, max_length=50000)
    reply_to_message_id: Optional[str] = None

    @validator("content")
    def validate_content(cls, v):
        return v.strip()


class SendMessageResponse(BaseModel):
    success: bool
    message: Optional[ChatMessage] = None
    error: Optional[str] = None


class SendThreadReplyRequest(BaseModel):
    """Request model for sending thread replies"""

    content: str = Field(..., min_length=1, max_length=50000)
    message_type: MessageType = MessageType.TEXT

    @validator("content")
    def validate_content(cls, v):
        return v.strip()


class EditMessageRequest(BaseModel):
    message_id: str
    new_content: str = Field(..., min_length=1, max_length=50000)


class ReactToMessageRequest(BaseModel):
    message_id: str
    reaction_type: ReactionType
    content: str = Field(description="Emoji unicode or GIF URL")


class PinMessageRequest(BaseModel):
    message_id: str
    reason: Optional[str] = None


class MessageHistoryRequest(BaseModel):
    club_id: str
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)
    before_message_id: Optional[str] = None  # For cursor-based pagination


class MessageHistoryResponse(BaseModel):
    messages: List[ChatMessage]
    has_more: bool
    total_count: Optional[int] = None
    next_cursor: Optional[str] = None


class UnreadMessageInfo(BaseModel):
    club_id: str
    club_name: str
    unread_count: int
    last_message: Optional[ChatMessage] = None
    last_read_message_id: Optional[str] = None


class UnreadSummaryResponse(BaseModel):
    total_unread: int
    clubs: List[UnreadMessageInfo]


class LokerRoomAccessResponse(BaseModel):
    has_access: bool
    user_role: Optional[UserRole] = None
    membership_status: Optional[MembershipStatus] = None
    is_muted: bool = Field(default=False)
    club_name: str
    member_count: int = Field(default=0)
    restrictions: List[str] = Field(default=[])


class MuteUserRequest(BaseModel):
    user_id: str
    reason: Optional[str] = None
    duration_hours: Optional[int] = None  # None means permanent


class MuteUserResponse(BaseModel):
    success: bool
    message: str
    muted_until: Optional[datetime] = None


# Socket.IO Event Models (moved to core/socket)
class SocketEvent(BaseModel):
    event: str
    data: Dict
    room: str = Field(description="Club ID for room targeting")


class UserJoinedEvent(BaseModel):
    event: Literal["user_joined"] = "user_joined"
    user: ChatUser
    club_id: str
    timestamp: datetime


class UserLeftEvent(BaseModel):
    event: Literal["user_left"] = "user_left"
    user_id: str
    username: str
    club_id: str
    timestamp: datetime


class NewMessageEvent(BaseModel):
    event: Literal["new_message"] = "new_message"
    message: ChatMessage
    mention_user_ids: List[str] = Field(default=[])


class MessageEditedEvent(BaseModel):
    event: Literal["message_edited"] = "message_edited"
    message: ChatMessage


class MessageDeletedEvent(BaseModel):
    event: Literal["message_deleted"] = "message_deleted"
    message_id: str
    club_id: str
    deleted_by: str


class MessageReactionEvent(BaseModel):
    event: Literal["message_reaction"] = "message_reaction"
    message_id: str
    reaction: MessageReaction
    club_id: str


class MessagePinnedEvent(BaseModel):
    event: Literal["message_pinned"] = "message_pinned"
    message: ChatMessage
    club_id: str


class TypingEvent(BaseModel):
    event: Literal["user_typing"] = "user_typing"
    user_id: str
    username: str
    club_id: str
    is_typing: bool


# Database Models
class ChatMessageDocument(BaseModel):
    """MongoDB document model for chat messages"""

    message_id: str
    club_id: str
    sender_id: str
    message_type: str
    content: dict
    reactions: List[dict] = Field(default=[])
    pinned: Optional[dict] = None
    reply_to_message_id: Optional[str] = None
    edited_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    is_deleted: bool = Field(default=False)


class UserAccessDocument(BaseModel):
    """MongoDB document for tracking user access to clubs"""

    user_id: str
    club_id: str
    role: str
    membership_status: str
    is_muted: bool = Field(default=False)
    muted_until: Optional[datetime] = None
    muted_by: Optional[str] = None
    muted_reason: Optional[str] = None
    last_seen: Optional[datetime] = None
    joined_at: datetime
    updated_at: datetime


class UnreadTrackingDocument(BaseModel):
    """MongoDB document for tracking unread messages"""

    user_id: str
    club_id: str
    last_read_message_id: Optional[str] = None
    last_read_at: Optional[datetime] = None
    unread_count: int = Field(default=0)
    updated_at: datetime


class ConnectedUserDocument(BaseModel):
    """MongoDB document for tracking connected users (moved to core/socket)"""

    user_id: str
    club_id: str
    socket_id: str
    connected_at: datetime
    last_activity: datetime


class FileType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    DOCUMENT = "document"
    AUDIO = "audio"


class FileUploadRequest(BaseModel):
    club_id: str
    file_type: FileType
    title: Optional[str] = None
    description: Optional[str] = None
    tags: List[str] = Field(default=[])


class FileUploadResponse(BaseModel):
    success: bool
    file_id: str
    file_url: str
    file_type: FileType
    title: Optional[str] = None
    description: Optional[str] = None
    uploaded_by: str
    uploaded_at: datetime
    file_size: int
    mime_type: str


class FileInfo(BaseModel):
    file_id: str
    file_url: str
    file_type: FileType
    title: Optional[str] = None
    description: Optional[str] = None
    uploaded_by: str
    uploaded_by_username: str
    uploaded_at: datetime
    file_size: int
    mime_type: str
    tags: List[str] = Field(default=[])


class FileListResponse(BaseModel):
    files: List[FileInfo]
    total_count: int
    has_more: bool


class MentionRequest(BaseModel):
    club_id: str
    message_content: str = Field(..., min_length=1, max_length=50000)
    mentioned_user_ids: List[str] = Field(default=[])
    reply_to_message_id: Optional[str] = None


class MentionResponse(BaseModel):
    success: bool
    message_id: str
    mentions: List[UserMention]
    message: ChatMessage


# Thread Models
class Thread(BaseModel):
    thread_id: str
    club_id: str
    parent_message_id: str
    title: str
    created_by: str
    created_by_username: str
    created_by_full_name: str
    status: ThreadStatus = ThreadStatus.ACTIVE
    message_count: int = 0
    last_message_at: Optional[datetime] = None
    last_message_by: Optional[str] = None
    last_message_by_username: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ThreadMessage(BaseModel):
    thread_message_id: str
    thread_id: str
    club_id: str
    sender_id: str
    sender_username: str
    sender_full_name: str
    sender_avatar: Optional[str] = None
    sender_role: UserRole
    message_type: MessageType
    content: MessageContent
    reactions: List[MessageReaction] = Field(default=[])
    reply_to_thread_message_id: Optional[str] = None
    reply_to_message_content: Optional[str] = (
        None  # Preview of the message being replied to
    )
    reply_to_sender_username: Optional[str] = (
        None  # Username of the message being replied to
    )
    reply_depth: int = 0  # How deep in the reply chain (0 = top level)
    edited_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class CreateThreadRequest(BaseModel):
    club_id: str
    parent_message_id: str
    title: str = Field(..., min_length=1, max_length=100)
    initial_message: str = Field(..., min_length=1, max_length=50000)

    @validator("title")
    def validate_title(cls, v):
        return v.strip()

    @validator("initial_message")
    def validate_initial_message(cls, v):
        return v.strip()


class CreateThreadResponse(BaseModel):
    success: bool
    thread_id: str
    thread: Thread
    message: str


class SendThreadMessageRequest(BaseModel):
    thread_id: str
    club_id: str
    content: str = Field(..., min_length=1, max_length=50000)
    message_type: MessageType = MessageType.TEXT
    reply_to_thread_message_id: Optional[str] = None


class ReplyToThreadMessageRequest(BaseModel):
    thread_id: str
    club_id: str
    reply_to_thread_message_id: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1, max_length=50000)
    message_type: MessageType = MessageType.TEXT

    @validator("content")
    def validate_content(cls, v):
        return v.strip()


class SendThreadMessageResponse(BaseModel):
    success: bool
    thread_message_id: str
    thread_message: ThreadMessage
    message: str


class ReplyToThreadMessageResponse(BaseModel):
    success: bool
    thread_message_id: str
    thread_message: ThreadMessage
    reply_to_message: Optional[ThreadMessage] = None
    message: str


class GetThreadsRequest(BaseModel):
    club_id: str
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    status: Optional[ThreadStatus] = None
    sort_by: str = Field(
        default="last_message", pattern="^(created_at|last_message|message_count)$"
    )


class GetThreadsResponse(BaseModel):
    success: bool
    threads: List[Thread]
    total_count: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool


class GetThreadMessagesRequest(BaseModel):
    thread_id: str
    club_id: str
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)


class GetThreadMessagesResponse(BaseModel):
    success: bool
    thread: Thread
    messages: List[ThreadMessage]
    total_count: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool


class UpdateThreadRequest(BaseModel):
    thread_id: str
    club_id: str
    title: Optional[str] = Field(None, min_length=1, max_length=100)
    status: Optional[ThreadStatus] = None

    @validator("title")
    def validate_title(cls, v):
        if v is not None:
            return v.strip()
        return v


class UpdateThreadResponse(BaseModel):
    success: bool
    thread: Thread
    message: str


class DeleteThreadRequest(BaseModel):
    thread_id: str
    club_id: str


class DeleteThreadResponse(BaseModel):
    success: bool
    message: str


class GetThreadMessageRepliesRequest(BaseModel):
    thread_id: str
    club_id: str
    thread_message_id: str
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class GetThreadMessageRepliesResponse(BaseModel):
    success: bool
    replies: List[ThreadMessage]
    total_count: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool
    message: str


# DM Request Models
class DMRequestStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    BLOCKED = "blocked"


class DMRequest(BaseModel):
    request_id: str
    sender_id: str
    sender_username: str
    sender_full_name: str
    sender_avatar: Optional[str] = None
    receiver_id: str
    receiver_username: str
    receiver_full_name: str
    receiver_avatar: Optional[str] = None
    club_id: str
    club_name: str
    status: DMRequestStatus = DMRequestStatus.PENDING
    message: Optional[str] = None  # Optional message with the request
    created_at: datetime
    updated_at: datetime
    block_status: Optional[dict] = None  # Block status information for action buttons
    responded_at: Optional[datetime] = None


class CreateDMRequestRequest(BaseModel):
    receiver_id: str = Field(..., min_length=1)
    club_id: str = Field(..., min_length=1)
    message: Optional[str] = Field(None, max_length=500)


class CreateDMRequestResponse(BaseModel):
    success: bool
    request_id: str
    dm_request: DMRequest
    message: str


class RespondToDMRequestRequest(BaseModel):
    request_id: str = Field(..., min_length=1)
    action: str = Field(..., pattern="^(accept|reject|block|unblock)$")


class RespondToDMRequestResponse(BaseModel):
    success: bool
    dm_request: Optional[DMRequest] = None  # None for reject action (request deleted)
    message: str


class GetDMRequestsRequest(BaseModel):
    club_id: Optional[str] = None
    status: Optional[DMRequestStatus] = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class GetDMRequestsResponse(BaseModel):
    success: bool
    requests: List[DMRequest]
    total_count: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool
    message: str


class BlockUserRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    club_id: str = Field(..., min_length=1)
    reason: Optional[str] = Field(None, max_length=500)


class BlockUserResponse(BaseModel):
    success: bool
    blocked_user_id: str
    message: str


class UnblockUserRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    club_id: str = Field(..., min_length=1)


class UnblockUserResponse(BaseModel):
    success: bool
    unblocked_user_id: str
    message: str


class GetBlockedUsersResponse(BaseModel):
    success: bool
    blocked_users: List[dict]
    total_count: int
    message: str


# DM Message Models
class DMMessage(BaseModel):
    dm_message_id: str
    sender_id: str
    sender_username: str
    sender_full_name: str
    sender_avatar: Optional[str] = None
    receiver_id: str
    receiver_username: str
    receiver_full_name: str
    receiver_avatar: Optional[str] = None
    club_id: str
    club_name: str
    content: MessageContent
    message_type: MessageType = MessageType.TEXT
    reactions: List[MessageReaction] = Field(default=[])
    reply_to_dm_message_id: Optional[str] = None
    edited_at: Optional[datetime] = None
    pinned: bool = Field(default=False, description="Whether the message is pinned")
    pinned_by: Optional[str] = Field(
        default=None, description="User ID who pinned the message"
    )
    pinned_by_username: Optional[str] = Field(
        default=None, description="Username who pinned the message"
    )
    pinned_at: Optional[datetime] = Field(
        default=None, description="When the message was pinned"
    )
    pin_reason: Optional[str] = Field(default=None, description="Reason for pinning")
    created_at: datetime
    updated_at: datetime


class SendDMMessageRequest(BaseModel):
    receiver_id: str = Field(..., min_length=1)
    club_id: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1, max_length=50000)
    message_type: MessageType = MessageType.TEXT
    reply_to_dm_message_id: Optional[str] = None


class SendDMMessageResponse(BaseModel):
    success: bool
    dm_message_id: str
    dm_message: DMMessage
    message: str


class GetDMMessagesRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    club_id: str = Field(..., min_length=1)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)
    before_message_id: Optional[str] = None
    search: Optional[str] = Field(
        default=None, description="Search query to filter messages by content"
    )


class GetDMMessagesResponse(BaseModel):
    success: bool
    messages: List[DMMessage]
    total_count: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool
    message: str


class GetDMConversationsRequest(BaseModel):
    club_id: str = Field(..., min_length=1)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class DMConversation(BaseModel):
    user_id: str
    username: str
    full_name: str
    avatar: Optional[str] = None
    last_message: Optional[DMMessage] = None
    unread_count: int = 0
    last_message_at: Optional[datetime] = None


class GetDMConversationsResponse(BaseModel):
    success: bool
    conversations: List[DMConversation]
    total_count: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool
    message: str


# DM Pin/Unpin Models
class PinDMMessageRequest(BaseModel):
    reason: Optional[str] = Field(
        default=None, max_length=200, description="Reason for pinning the message"
    )


class GetDMPinnedMessagesRequest(BaseModel):
    user_id: str = Field(
        ..., min_length=1, description="User ID to get pinned messages for"
    )
    club_id: str = Field(..., min_length=1, description="Club ID")
    page: int = Field(default=1, ge=1, description="Page number")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page")


class GetDMPinnedMessagesResponse(BaseModel):
    success: bool
    pinned_messages: List[DMMessage]
    total_count: int
    page: int
    page_size: int
    total_pages: int


class EditDMMessageRequest(BaseModel):
    dm_message_id: str = Field(..., min_length=1)
    new_content: str = Field(..., min_length=1, max_length=50000)

    @validator("new_content")
    def validate_content(cls, v):
        return v.strip()


class EditDMMessageResponse(BaseModel):
    success: bool
    dm_message: DMMessage
    message: str


class DeleteDMMessageRequest(BaseModel):
    dm_message_id: str = Field(..., min_length=1)


class DeleteDMMessageResponse(BaseModel):
    success: bool
    message: str


# DM Thread Message Models
class SendDMThreadMessageRequest(BaseModel):
    receiver_id: str = Field(..., min_length=1)
    club_id: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1, max_length=50000)
    message_type: MessageType = MessageType.TEXT
    parent_dm_message_id: str = Field(
        ..., min_length=1, description="Parent DM message ID to reply to"
    )


class SendDMThreadMessageResponse(BaseModel):
    success: bool
    dm_message_id: str
    dm_message: DMMessage
    parent_dm_message_id: str
    thread_count: int
    message: str


class GetDMThreadMessagesRequest(BaseModel):
    receiver_id: str = Field(..., min_length=1)
    club_id: str = Field(..., min_length=1)
    parent_dm_message_id: str = Field(
        ..., min_length=1, description="Parent DM message ID to get thread for"
    )
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=100)


class GetDMThreadMessagesResponse(BaseModel):
    success: bool
    parent_dm_message_id: str
    thread_messages: List[DMMessage]
    total_count: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool
    message: str


# Member Clubs Latest Messages Models
class MemberClubLatestMessage(BaseModel):
    club_id: str
    club_name: str
    name_based_id: str
    club_logo: Optional[str] = None
    latest_message: Optional[ChatMessage] = None
    latest_message_sender: Optional[dict] = (
        None  # {user_id, username, full_name, role, avatar}
    )
    latest_message_time: Optional[datetime] = None
    unread_count: int = 0
    membership_type: str  # "trial" or "paid"
    membership_status: str  # "active" or "inactive"
    join_date: Optional[datetime] = None
    trial_end_date: Optional[datetime] = None
    paid_end_date: Optional[datetime] = None


class GetMemberClubsLatestMessagesRequest(BaseModel):
    page: int = Field(default=1, ge=1, description="Page number")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page")
    sort_by: str = Field(
        default="latest_message",
        pattern="^(latest_message|club_name|join_date)$",
        description="Sort by latest_message, club_name, or join_date",
    )


class GetMemberClubsLatestMessagesResponse(BaseModel):
    success: bool
    clubs: List[MemberClubLatestMessage]
    total_count: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool
    message: str


# Club Detail Page Models
class ClubMember(BaseModel):
    user_id: str
    username: str
    full_name: str
    email: Optional[str] = None
    avatar_url: Optional[str] = None
    role: str  # "Captain", "Moderator", "Member"
    membership_type: str  # "trial", "paid"
    membership_status: str  # "active", "inactive"
    join_date: Optional[datetime] = None
    trial_end_date: Optional[datetime] = None
    paid_end_date: Optional[datetime] = None
    pricing_plan: Optional[str] = None  # "trial", "monthly", "yearly", etc.
    is_muted: bool = False
    last_seen: Optional[datetime] = None
    # DM Request fields
    dm_requests_sent: List["DMRequestInfo"] = Field(default=[])
    dm_requests_received: List["DMRequestInfo"] = Field(default=[])
    total_dm_requests_sent: int = 0
    total_dm_requests_received: int = 0
    pending_dm_requests_sent: int = 0
    pending_dm_requests_received: int = 0


class ClubModerator(BaseModel):
    user_id: str
    username: str
    full_name: str
    email: Optional[str] = None
    avatar_url: Optional[str] = None
    role: str = "Moderator"
    assigned_by: str  # Captain who assigned this moderator
    assigned_at: Optional[datetime] = None
    permissions: List[str] = Field(
        default=[], description="List of moderator permissions"
    )


class ClubDetailResponse(BaseModel):
    success: bool
    club_id: str
    club_name: str
    name_based_id: str
    description: Optional[str] = None
    logo_url: Optional[str] = None
    banner_url: Optional[str] = None
    status: str  # "active", "inactive", "pending", "suspended"
    created_at: datetime
    updated_at: datetime

    # User's relationship with the club
    user_role: str  # "Captain", "Moderator", "Member", "None"
    user_membership_type: Optional[str] = None  # "trial", "paid"
    user_membership_status: Optional[str] = None  # "active", "inactive"
    user_join_date: Optional[datetime] = None
    user_trial_end_date: Optional[datetime] = None
    user_paid_end_date: Optional[datetime] = None
    user_is_muted: bool = False

    # Club statistics
    total_members: int
    total_moderators: int
    total_paid_members: int
    total_trial_members: int
    monthly_revenue: float = 0.0

    # Club details
    captain: Optional[ClubMember] = None
    moderators: List[ClubModerator] = Field(default=[])
    members: List[ClubMember] = Field(default=[])
    paid_members: List[ClubMember] = Field(default=[])
    trial_members: List[ClubMember] = Field(default=[])

    # Pricing information
    pricing: Optional[dict] = None
    pricing_plans: List[dict] = Field(default=[])

    # Club settings
    settings: Optional[dict] = None

    message: str


# ========================================
# User Status in Club Models
# ========================================


class DMRequestInfo(BaseModel):
    """DM request status for a user"""

    request_id: str
    sender_id: str
    sender_name: str
    receiver_id: str
    receiver_name: str
    status: str  # pending, accepted, rejected, cancelled
    created_at: datetime
    updated_at: Optional[datetime] = None
    message: Optional[str] = None


class UserClubStatus(BaseModel):
    """User status in a specific club"""

    user_id: str
    full_name: str
    email: str
    phone: str
    avatar_url: Optional[str] = None
    role: str  # Captain, Moderator, Member
    membership_type: str  # trial, paid
    membership_status: str  # active, inactive
    is_muted: bool = False
    last_visited: Optional[datetime] = None
    join_date: datetime
    is_active: bool = True
    dm_requests_sent: List[DMRequestInfo] = Field(default=[])
    dm_requests_received: List[DMRequestInfo] = Field(default=[])
    total_dm_requests_sent: int = 0
    total_dm_requests_received: int = 0
    pending_dm_requests_sent: int = 0
    pending_dm_requests_received: int = 0


class ClubMemberStatus(BaseModel):
    """Club member with detailed status information"""

    user_id: str
    full_name: str
    email: str
    phone: str
    avatar_url: Optional[str] = None
    role: str
    membership_type: str
    membership_status: str
    is_muted: bool = False
    last_visited: Optional[datetime] = None
    join_date: datetime
    is_active: bool = True
    dm_requests_sent: List[DMRequestInfo] = Field(default=[])
    dm_requests_received: List[DMRequestInfo] = Field(default=[])
    total_dm_requests_sent: int = 0
    total_dm_requests_received: int = 0
    pending_dm_requests_sent: int = 0
    pending_dm_requests_received: int = 0


class ClubModeratorStatus(BaseModel):
    """Club moderator with detailed status information including is_register field"""

    user_id: str
    full_name: str
    email: str
    phone: str
    avatar_url: Optional[str] = None
    role: str
    membership_type: str
    membership_status: str
    is_muted: bool = False
    last_visited: Optional[datetime] = None
    join_date: datetime
    is_active: bool = True
    is_register: bool = True
    dm_requests_sent: List[DMRequestInfo] = Field(default=[])
    dm_requests_received: List[DMRequestInfo] = Field(default=[])
    total_dm_requests_sent: int = 0
    total_dm_requests_received: int = 0
    pending_dm_requests_sent: int = 0
    pending_dm_requests_received: int = 0


class UserClubStatusResponse(BaseModel):
    """Response model for user status in club API"""

    success: bool
    message: str
    data: Optional[dict] = None


class ClubMemberStatusResponse(BaseModel):
    """Response model for club member status API"""

    success: bool
    message: str
    data: Optional[dict] = None


# Pagination Request Models
class PaginationRequest(BaseModel):
    """Base pagination request model"""

    page: int = Field(default=1, ge=1, description="Page number (1-based)")
    page_size: int = Field(
        default=10, ge=1, le=100, description="Number of items per page"
    )


# Paginated Response Models for Club Members by Role
class ClubCaptainsResponse(BaseModel):
    """Response model for club captains with pagination"""

    success: bool
    message: str
    data: Optional[dict] = None


class ClubModeratorsResponse(BaseModel):
    """Response model for club moderators with pagination"""

    success: bool
    message: str
    data: Optional[dict] = None


class ClubMembersResponse(BaseModel):
    """Response model for club members with pagination"""

    success: bool
    message: str
    data: Optional[dict] = None


# Connected DM Users Models
class ConnectedDMUser(BaseModel):
    """Model for a connected DM user with last message info"""

    user_id: str
    username: str
    full_name: str
    avatar_url: Optional[str] = None
    last_message: Optional[str] = None  # Last message content
    last_message_timestamp: Optional[datetime] = None
    last_message_sender_id: Optional[str] = None  # Who sent the last message
    last_message_sender_username: Optional[str] = None
    last_message_sender_full_name: Optional[str] = None
    unread_count: int = 0
    status: Optional[str] = (
        None  # Blocking status: "active", "blocked_by_me", "blocked_by_other", "mutual_block"
    )
    blocked_by: Optional[str] = None  # Who blocked whom: "me", "other", "mutual", None
    blocked_at: Optional[datetime] = None  # When the blocking occurred
    is_dm_chat_open: bool = True  # Whether DM chat is currently open for this user (defaults to True)


class GetConnectedDMUsersRequest(BaseModel):
    """Request model for getting connected DM users"""

    club_id: str = Field(..., min_length=1, description="Club name_based_id")
    search: Optional[str] = Field(
        default=None,
        description="Search query to filter users by username or full name",
    )
    page: int = Field(default=1, ge=1, description="Page number")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page")


class GetConnectedDMUsersResponse(BaseModel):
    """Response model for connected DM users"""

    success: bool
    connected_users: List[ConnectedDMUser]
    total_count: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_previous: bool
    message: str


# Resolve forward references
ClubMember.model_rebuild()
