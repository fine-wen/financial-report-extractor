from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    unified_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    documents: Mapped[list["Document"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    fields: Mapped[list["ExtractedField"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    processing_mode: Mapped[str] = mapped_column(String(32), default="auto")
    document_type: Mapped[str] = mapped_column(String(48), default="auto")
    mineru_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mineru_task_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    scan_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    scan_source_page_count: Mapped[int | None] = mapped_column(nullable=True)
    mineru_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mineru_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    page_count: Mapped[int | None] = mapped_column(nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    company: Mapped[Company] = relationship(back_populates="documents")
    fields: Mapped[list["ExtractedField"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class ExtractedField(Base):
    __tablename__ = "extracted_fields"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    field_code: Mapped[str] = mapped_column(String(100), index=True)
    label: Mapped[str] = mapped_column(String(100))
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 4), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    period: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_page: Mapped[int | None] = mapped_column(nullable=True)
    source_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    original_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    company: Mapped[Company] = relationship(back_populates="fields")
    document: Mapped[Document] = relationship(back_populates="fields")


class ManualMetricDecision(Base):
    __tablename__ = "manual_metric_decisions"
    __table_args__ = (UniqueConstraint("document_id", "field_code", "period"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    field_code: Mapped[str] = mapped_column(String(100))
    period: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 4), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_page: Mapped[int | None] = mapped_column(nullable=True)
    source_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str] = mapped_column(String(100))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MetricRelationException(Base):
    __tablename__ = "metric_relation_exceptions"
    __table_args__ = (UniqueConstraint("document_id", "period", "part_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    period: Mapped[str] = mapped_column(String(32))
    part_code: Mapped[str] = mapped_column(String(100))
    part_value: Mapped[Decimal] = mapped_column(Numeric(24, 4))
    total_value: Mapped[Decimal] = mapped_column(Numeric(24, 4))
    source_page: Mapped[int] = mapped_column()
    source_quote: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    reviewed_by: Mapped[str] = mapped_column(String(100))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str] = mapped_column(String(100))
    actor: Mapped[str] = mapped_column(String(100))
    details: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
