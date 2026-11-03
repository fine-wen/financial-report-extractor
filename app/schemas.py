from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CompanyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    unified_code: str | None = Field(max_length=32)
    industry: str | None = Field(max_length=100)
    contact_name: str | None = Field(max_length=100)


class CompanyBatchCreate(BaseModel):
    companies: list[CompanyCreate] = Field(min_length=1, max_length=200)


class CompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    unified_code: str | None
    industry: str | None
    contact_name: str | None
    created_at: datetime
    document_count: int = 0
    pending_count: int = 0
    confirmed_count: int = 0


class CompanyBatchRead(BaseModel):
    created: list[CompanyRead]
    skipped_names: list[str]


class DocumentCheckSummary(BaseModel):
    periods: list[str]
    statement_scope: str | None
    base_field_count: int
    calculated_field_count: int
    pending_count: int
    reviewed_count: int
    high_priority_count: int
    suspicious_count: int
    balance_sheet_status: str
    income_statement_status: str
    cash_flow_statement_status: str
    balance_status: str
    balance_periods: list[str]


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    filename: str
    sha256: str
    status: str
    processing_mode: str
    document_type: str
    mineru_task_id: str | None
    mineru_task_status: str | None
    scan_stage: str | None
    scan_source_page_count: int | None
    mineru_submitted_at: datetime | None
    mineru_heartbeat_at: datetime | None
    page_count: int | None
    error_message: str | None
    created_at: datetime
    processed_at: datetime | None
    field_count: int = 0
    check_summary: DocumentCheckSummary | None = None


class FieldRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    document_id: int
    field_code: str
    label: str
    value_text: str | None
    normalized_value: Decimal | None
    unit: str | None
    period: str | None
    source_page: int | None
    source_quote: str | None
    confidence: Decimal
    status: str
    original_value: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    document_filename: str | None = None
    company_name: str | None = None
    review_priority: str = "normal"
    risk_reasons: list[str] = Field(default_factory=list)


class FieldReview(BaseModel):
    status: str
    value_text: str | None
    unit: str | None
    period: str | None
    source_page: int | None = Field(default=None, ge=1)
    source_quote: str | None = None
    reviewer: str = Field(min_length=1, max_length=100)


class BatchConfirm(BaseModel):
    field_ids: list[int] = Field(min_length=1)
    reviewer: str = Field(min_length=1, max_length=100)


class DashboardRead(BaseModel):
    company_count: int
    document_count: int
    processing_count: int
    failed_count: int
    pending_field_count: int
    confirmed_field_count: int


class FinancialSnapshotItem(BaseModel):
    field_code: str
    label: str
    value_text: str | None
    normalized_value: Decimal | None
    unit: str | None
    period: str | None
    status: str
    source_page: int | None
    source_quote: str | None
    document_filename: str | None = None


class MetricOptionRead(BaseModel):
    code: str
    label: str


class BatchDocumentUploadItem(BaseModel):
    relative_path: str
    company_name: str | None
    filename: str
    status: str
    document_id: int | None
    message: str | None


class BatchDocumentUploadRead(BaseModel):
    created_company_count: int
    uploaded_count: int
    duplicate_count: int
    failed_count: int
    items: list[BatchDocumentUploadItem]
