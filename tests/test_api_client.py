"""Tests for aula.api_client."""

import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aula.api_client import AulaApiClient
from aula.http import HttpResponse


class TestGetPresenceTemplates:
    """Tests for AulaApiClient.get_presence_templates method."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock API client."""
        http_client = AsyncMock()
        client = AulaApiClient(
            http_client=http_client,
            access_token="test_token",
        )
        return client

    @pytest.mark.asyncio
    async def test_get_presence_templates_happy_path(self, mock_client):
        """Test fetching presence templates with valid data."""
        from aula.models.presence_template import PresenceWeekTemplate

        response_data = {
            "data": {
                "presenceWeekTemplates": [
                    {
                        "institutionProfile": {
                            "id": 10,
                            "profileId": 99,
                            "institutionName": "School",
                        },
                        "dayTemplates": [
                            {
                                "id": 1,
                                "byDate": "2026-02-25",
                                "entryTime": "08:00",
                                "exitTime": "16:00",
                            }
                        ],
                    }
                ]
            }
        }

        mock_client._request_with_version_retry = AsyncMock()
        mock_response = HttpResponse(status_code=200, data=response_data)
        mock_response.raise_for_status = MagicMock()
        mock_client._request_with_version_retry.return_value = mock_response

        result = await mock_client.get_presence_templates(
            [10, 20],
            date(2026, 2, 25),
            date(2026, 2, 25),
        )

        assert len(result) == 1
        assert isinstance(result[0], PresenceWeekTemplate)
        assert result[0].institution_profile is not None
        assert result[0].institution_profile.id == 10
        assert len(result[0].day_templates) == 1
        assert result[0].day_templates[0].by_date == "2026-02-25"

    @pytest.mark.asyncio
    async def test_get_presence_templates_empty_list(self, mock_client):
        """Test fetching with empty templates list."""
        response_data = {
            "data": {
                "presenceWeekTemplates": []
            }
        }

        mock_client._request_with_version_retry = AsyncMock()
        mock_response = HttpResponse(status_code=200, data=response_data)
        mock_response.raise_for_status = MagicMock()
        mock_client._request_with_version_retry.return_value = mock_response

        result = await mock_client.get_presence_templates(
            [10],
            date(2026, 2, 25),
            date(2026, 2, 25),
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_get_presence_templates_null_data(self, mock_client):
        """Test handling when data field is null."""
        response_data = {
            "data": None
        }

        mock_client._request_with_version_retry = AsyncMock()
        mock_response = HttpResponse(status_code=200, data=response_data)
        mock_response.raise_for_status = MagicMock()
        mock_client._request_with_version_retry.return_value = mock_response

        result = await mock_client.get_presence_templates(
            [10],
            date(2026, 2, 25),
            date(2026, 2, 25),
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_get_presence_templates_null_presenceWeekTemplates(self, mock_client):
        """Test handling when presenceWeekTemplates is null."""
        response_data = {
            "data": {
                "presenceWeekTemplates": None
            }
        }

        mock_client._request_with_version_retry = AsyncMock()
        mock_response = HttpResponse(status_code=200, data=response_data)
        mock_response.raise_for_status = MagicMock()
        mock_client._request_with_version_retry.return_value = mock_response

        result = await mock_client.get_presence_templates(
            [10],
            date(2026, 2, 25),
            date(2026, 2, 25),
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_get_presence_templates_null_items_in_list(self, mock_client):
        """Test handling when list contains null items."""
        response_data = {
            "data": {
                "presenceWeekTemplates": [
                    {
                        "institutionProfile": {"id": 10},
                        "dayTemplates": [{"id": 1, "byDate": "2026-02-25"}],
                    },
                    None,  # null item should be skipped
                    {
                        "institutionProfile": {"id": 20},
                        "dayTemplates": [{"id": 2, "byDate": "2026-02-25"}],
                    },
                ]
            }
        }

        mock_client._request_with_version_retry = AsyncMock()
        mock_response = HttpResponse(status_code=200, data=response_data)
        mock_response.raise_for_status = MagicMock()
        mock_client._request_with_version_retry.return_value = mock_response

        result = await mock_client.get_presence_templates(
            [10, 20],
            date(2026, 2, 25),
            date(2026, 2, 25),
        )

        # Should skip the null item and return 2 valid templates
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_presence_templates_malformed_item(self, mock_client, caplog):
        """Test handling of malformed template item."""
        response_data = {
            "data": {
                "presenceWeekTemplates": [
                    {
                        "institutionProfile": {"id": 10},
                        "dayTemplates": [{"id": 1, "byDate": "2026-02-25"}],
                    },
                    {
                        "dayTemplates": [{"id": 2}],
                        # Missing institutionProfile - might cause error
                    },
                    {
                        "institutionProfile": {"id": 30},
                        "dayTemplates": [{"id": 3, "byDate": "2026-02-26"}],
                    },
                ]
            }
        }

        mock_client._request_with_version_retry = AsyncMock()
        mock_response = HttpResponse(status_code=200, data=response_data)
        mock_response.raise_for_status = MagicMock()
        mock_client._request_with_version_retry.return_value = mock_response

        with caplog.at_level("WARNING"):
            result = await mock_client.get_presence_templates(
                [10, 20, 30],
                date(2026, 2, 25),
                date(2026, 2, 25),
            )

        # Should return valid templates and skip/log the malformed one
        assert len(result) >= 2  # At least the two valid ones

    @pytest.mark.asyncio
    async def test_get_presence_templates_non_dict_presenceWeekTemplates(self, mock_client):
        """Test handling when presenceWeekTemplates is not a list."""
        response_data = {
            "data": {
                "presenceWeekTemplates": "not a list"
            }
        }

        mock_client._request_with_version_retry = AsyncMock()
        mock_response = HttpResponse(status_code=200, data=response_data)
        mock_response.raise_for_status = MagicMock()
        mock_client._request_with_version_retry.return_value = mock_response

        result = await mock_client.get_presence_templates(
            [10],
            date(2026, 2, 25),
            date(2026, 2, 25),
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_get_presence_templates_string_data(self, mock_client):
        """Test handling when data is a string instead of dict."""
        response_data = {
            "data": "string instead of dict"
        }

        mock_client._request_with_version_retry = AsyncMock()
        mock_response = HttpResponse(status_code=200, data=response_data)
        mock_response.raise_for_status = MagicMock()
        mock_client._request_with_version_retry.return_value = mock_response

        result = await mock_client.get_presence_templates(
            [10],
            date(2026, 2, 25),
            date(2026, 2, 25),
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_get_presence_templates_non_dict_items(self, mock_client):
        """Test handling when list contains non-dict items."""
        response_data = {
            "data": {
                "presenceWeekTemplates": [
                    {
                        "institutionProfile": {"id": 10},
                        "dayTemplates": [{"id": 1}],
                    },
                    "not a dict",
                    123,
                    {
                        "institutionProfile": {"id": 20},
                        "dayTemplates": [{"id": 2}],
                    },
                ]
            }
        }

        mock_client._request_with_version_retry = AsyncMock()
        mock_response = HttpResponse(status_code=200, data=response_data)
        mock_response.raise_for_status = MagicMock()
        mock_client._request_with_version_retry.return_value = mock_response

        result = await mock_client.get_presence_templates(
            [10, 20],
            date(2026, 2, 25),
            date(2026, 2, 25),
        )

        # Should skip non-dict items and return 2 valid templates
        assert len(result) == 2
