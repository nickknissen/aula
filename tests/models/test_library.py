"""Tests for aula.models.library."""

from aula.models.library import LibraryLoan, LibraryStatus


def test_library_loan_from_dict():
    data = {
        "id": 42,
        "title": "The Hobbit",
        "author": "Tolkien",
        "patronDisplayName": "Alice",
        "dueDate": "2025-06-01",
        "numberOfLoans": 3,
        "coverImageUrl": "https://example.com/cover.jpg",
    }
    loan = LibraryLoan.from_dict(data)
    assert loan.id == 42
    assert loan.title == "The Hobbit"
    assert loan.author == "Tolkien"
    assert loan.patron_display_name == "Alice"
    assert loan.due_date == "2025-06-01"
    assert loan.number_of_loans == 3
    assert loan.cover_image_url == "https://example.com/cover.jpg"
    assert loan._raw is data


def test_library_loan_from_dict_defaults():
    data = {}
    loan = LibraryLoan.from_dict(data)
    assert loan.id == 0
    assert loan.title == ""
    assert loan.author == ""
    assert loan.number_of_loans == 0


def test_library_status_from_dict():
    data = {
        "loans": [
            {"id": 1, "title": "Book A", "author": "A", "patronDisplayName": "X",
             "dueDate": "2025-01-01", "numberOfLoans": 1},
        ],
        "longtermLoans": [
            {"id": 2, "title": "Book B", "author": "B", "patronDisplayName": "Y",
             "dueDate": "2025-12-01", "numberOfLoans": 2},
        ],
        "reservations": [{"id": "r1"}],
        "branchIds": ["branch1", "branch2"],
    }
    status = LibraryStatus.from_dict(data)
    assert len(status.loans) == 1
    assert status.loans[0].title == "Book A"
    assert len(status.longterm_loans) == 1
    assert status.longterm_loans[0].title == "Book B"
    assert len(status.reservations) == 1
    assert status.branch_ids == ["branch1", "branch2"]
    assert status._raw is data


def test_library_status_from_dict_empty():
    data = {}
    status = LibraryStatus.from_dict(data)
    assert status.loans == []
    assert status.longterm_loans == []
    assert status.reservations == []
    assert status.branch_ids == []


def test_library_loan_dict_conversion():
    loan = LibraryLoan(
        id=1, title="Book", author="Author",
        patron_display_name="Reader", due_date="2025-01-01",
        number_of_loans=1, cover_image_url="",
    )
    result = dict(loan)
    assert result["title"] == "Book"
    assert "_raw" not in result
