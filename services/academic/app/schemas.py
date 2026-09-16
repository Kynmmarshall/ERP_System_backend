import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class PrincipalResponse(BaseModel):
    """Reflects the verified JWT claims - proves this service independently
    validated the token itself rather than trusting gateway headers alone."""

    user_id: str
    tenant_id: str | None
    role: str


class ProgramResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    code: str


class TermResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    starts_on: datetime
    ends_on: datetime


class EnrollmentCreateRequest(BaseModel):
    program_id: uuid.UUID
    term_id: uuid.UUID
    # Staff/admin may enroll a specific student; a student may only enroll themselves.
    student_id: uuid.UUID | None = None


class EnrollmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    program_id: uuid.UUID
    term_id: uuid.UUID
    student_id: uuid.UUID
    status: str
    created_at: datetime


class CourseCreateRequest(BaseModel):
    program_id: uuid.UUID
    code: str
    name: str
    credits: int = 3


class CourseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    program_id: uuid.UUID
    code: str
    name: str
    credits: int


class PrerequisiteCreateRequest(BaseModel):
    prerequisite_course_id: uuid.UUID


class PrerequisiteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    course_id: uuid.UUID
    prerequisite_course_id: uuid.UUID


class CourseOfferingCreateRequest(BaseModel):
    course_id: uuid.UUID
    term_id: uuid.UUID
    instructor_id: uuid.UUID
    room: str
    capacity: int = 50


class CourseOfferingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    course_id: uuid.UUID
    term_id: uuid.UUID
    instructor_id: uuid.UUID
    room: str
    capacity: int


class CourseRegistrationCreateRequest(BaseModel):
    course_offering_id: uuid.UUID
    enrollment_id: uuid.UUID


class CourseRegistrationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    student_id: uuid.UUID
    enrollment_id: uuid.UUID
    course_offering_id: uuid.UUID
    created_at: datetime


class AttendanceSessionCreateRequest(BaseModel):
    course_offering_id: uuid.UUID
    session_date: date


class AttendanceSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    course_offering_id: uuid.UUID
    session_date: date


class AttendanceMarkEntry(BaseModel):
    student_id: uuid.UUID
    present: bool


class AttendanceMarkRequest(BaseModel):
    records: list[AttendanceMarkEntry]


class AttendanceRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    attendance_session_id: uuid.UUID
    student_id: uuid.UUID
    present: bool


class AssessmentCreateRequest(BaseModel):
    course_offering_id: uuid.UUID
    name: str
    max_score: int = 100


class AssessmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    course_offering_id: uuid.UUID
    name: str
    max_score: int


class GradeEntry(BaseModel):
    student_id: uuid.UUID
    score: float


class GradeEntryRequest(BaseModel):
    grades: list[GradeEntry]


class GradeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    assessment_id: uuid.UUID
    student_id: uuid.UUID
    score: float
    published: bool


class GradeAppealCreateRequest(BaseModel):
    reason: str


class GradeAppealDecisionRequest(BaseModel):
    status: str
    reviewer_notes: str | None = None
    corrected_score: float | None = None


class GradeAppealResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    grade_id: uuid.UUID
    student_id: uuid.UUID
    reason: str
    status: str
    reviewer_notes: str | None
    decided_by: uuid.UUID | None
    decided_at: datetime | None


class ExamScheduleCreateRequest(BaseModel):
    course_offering_id: uuid.UUID
    room: str
    starts_at: datetime
    ends_at: datetime


class ExamScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    course_offering_id: uuid.UUID
    room: str
    starts_at: datetime
    ends_at: datetime


class AtRiskStatus(BaseModel):
    student_id: uuid.UUID
    course_offering_id: uuid.UUID
    attendance_rate: float | None
    assessment_average: float | None
    at_risk: bool
