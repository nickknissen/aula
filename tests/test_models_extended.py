"""Tests for remaining aula.models modules."""

from aula.models.appointment import Appointment
from aula.models.institution_profile import InstitutionProfile
from aula.models.library import LibraryLoan, LibraryStatus
from aula.models.main_group import MainGroup
from aula.models.message_thread import MessageThread
from aula.models.mu_task import MUTaskClass, MUTaskCourse, _parse_dotnet_date
from aula.models.mu_weekly_letter import (
    MUWeeklyInstitution,
    MUWeeklyLetter,
    MUWeeklyPerson,
)
from aula.models.presence import PresenceState
from aula.models.profile_picture import ProfilePicture
from aula.models.profile_reference import ProfileReference


def test_appointment_creation():
    appt = Appointment(appointment_id="a1", title="Meeting")
    assert dict(appt)["title"] == "Meeting"


def test_message_thread_creation():
    thread = MessageThread(thread_id="t1", subject="Hello")
    assert dict(thread)["subject"] == "Hello"


def test_profile_picture_creation():
    pic = ProfilePicture(url="https://example.com/pic.jpg")
    assert pic.url == "https://example.com/pic.jpg"


def test_profile_picture_none_url():
    pic = ProfilePicture()
    assert pic.url is None


def test_main_group_creation():
    mg = MainGroup(id=1, name="Group A")
    result = dict(mg)
    assert result["name"] == "Group A"


def test_institution_profile_creation():
    ip = InstitutionProfile(
        profile_id=1,
        institution_name="School",
        role="guardian",
    )
    assert ip.institution_name == "School"


def test_presence_state_values():
    assert PresenceState.NOT_PRESENT.value == 0
    assert PresenceState.PRESENT.value == 3
    assert PresenceState.SICK.value == 1


def test_presence_state_display_name():
    name = PresenceState.get_display_name(3)
    assert name is not None


def test_profile_reference_creation():
    ref = ProfileReference(
        id=1,
        profile_id=100,
        first_name="John",
        last_name="Doe",
        full_name="John Doe",
        short_name="JD",
        role="guardian",
        institution_name="School",
    )
    result = dict(ref)
    assert result["full_name"] == "John Doe"


def test_library_loan_creation():
    loan = LibraryLoan(
        id="1",
        title="Book",
        author="Author",
        patron_display_name="Reader",
        due_date="2025-01-01",
        number_of_loans=1,
        cover_image_url="",
    )
    assert loan.title == "Book"


def test_library_status_creation():
    status = LibraryStatus(
        loans=[],
        longterm_loans=[],
        reservations=[],
        branch_ids=[],
    )
    assert status.loans == []


def test_mu_task_class_creation():
    tc = MUTaskClass(id=1, name="Math", subject_id=10, subject_name="Mathematics")
    assert tc.name == "Math"


def test_mu_task_course_creation():
    course = MUTaskCourse(
        id=1, name="Course A", icon="icon.png", yearly_plan_id=5, color="#fff", url=""
    )
    assert course.name == "Course A"


def test_parse_dotnet_date():
    result = _parse_dotnet_date("/Date(1609459200000)/")
    assert result is not None
    assert result.year == 2021


def test_parse_dotnet_date_none():
    assert _parse_dotnet_date(None) is None
    assert _parse_dotnet_date("") is None
    assert _parse_dotnet_date("invalid") is None


def test_mu_weekly_letter_creation():
    letter = MUWeeklyLetter(
        group_id=1,
        group_name="Group",
        content_html="<p>Content</p>",
        week_number=5,
        sort_order=1,
    )
    assert letter.week_number == 5


def test_mu_weekly_institution_creation():
    inst = MUWeeklyInstitution(name="School", code="S1", letters=[])
    assert inst.name == "School"


def test_mu_weekly_person_creation():
    person = MUWeeklyPerson(name="Student", id=1, unilogin="user1", institutions=[])
    assert person.name == "Student"
