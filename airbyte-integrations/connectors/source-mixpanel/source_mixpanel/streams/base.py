#
# Copyright (c) 2022 Airbyte, Inc., all rights reserved.
#

import time
from abc import ABC
from datetime import date, datetime, timedelta
from typing import Any, Iterable, List, Mapping, MutableMapping, Optional, Union

import requests
from airbyte_cdk.sources.streams.http import HttpStream
from airbyte_cdk.sources.streams.http.auth import HttpAuthenticator


class MixpanelStream(HttpStream, ABC):
    """
    Formatted API Rate Limit  (https://help.mixpanel.com/hc/en-us/articles/115004602563-Rate-Limits-for-API-Endpoints):
      A maximum of 5 concurrent queries
      60 queries per hour.

    API Rate Limit Handler: after each request freeze for the time period: 3600/reqs_per_hour_limit seconds
    """

    @property
    def url_base(self):
        prefix = "eu." if self.region == "EU" else ""
        return f"https://{prefix}mixpanel.com/api/2.0/"

    # https://help.mixpanel.com/hc/en-us/articles/115004602563-Rate-Limits-for-Export-API-Endpoints#api-export-endpoint-rate-limits
    reqs_per_hour_limit: int = 0  # 1 query per minute

    def __init__(
        self,
        authenticator: HttpAuthenticator,
        region: str = None,
        start_date: Union[date, str] = None,
        end_date: Union[date, str] = None,
        date_window_size: int = 30,  # in days
        attribution_window: int = 0,  # in days
        select_properties_by_default: bool = True,
        projects: Optional[List] = None,
        **kwargs,
    ):
        self.start_date = start_date
        self.end_date = end_date
        self.date_window_size = date_window_size
        self.attribution_window = attribution_window
        self.additional_properties = select_properties_by_default
        self.region = region if region else "US"
        self.projects = [{'project_id': item['id']} for item in projects] if projects else None

        super().__init__(authenticator=authenticator)

    def next_page_token(self, response: requests.Response) -> Optional[Mapping[str, Any]]:
        """Define abstract method"""
        return None

    def request_headers(
        self, stream_state: Mapping[str, Any], stream_slice: Mapping[str, Any] = None, next_page_token: Mapping[str, Any] = None
    ) -> Mapping[str, Any]:
        return {"Accept": "application/json"}

    def _send_request(self, request: requests.PreparedRequest, request_kwargs: Mapping[str, Any]) -> requests.Response:
        try:
            return super()._send_request(request, request_kwargs)
        except requests.exceptions.HTTPError as e:
            error_message = e.response.text
            if error_message:
                self.logger.error(f"Stream {self.name}: {e.response.status_code} {e.response.reason} - {error_message}")
            raise e

    def process_response(self, response: requests.Response, **kwargs) -> Iterable[Mapping]:
        json_response = response.json()
        if self.data_field is not None:
            data = json_response.get(self.data_field, [])
        elif isinstance(json_response, list):
            data = json_response
        elif isinstance(json_response, dict):
            data = [json_response]

        for record in data:
            yield record

    def parse_response(self, response: requests.Response, **kwargs) -> Iterable[Mapping]:

        # parse the whole response
        yield from self.process_response(response, **kwargs)

        if self.reqs_per_hour_limit > 0:
            # we skip this block, if self.reqs_per_hour_limit = 0,
            # in all other cases wait for X seconds to match API limitations
            time.sleep(3600 / self.reqs_per_hour_limit)

    def get_stream_params(self) -> Mapping[str, Any]:
        """
        Fetch required parameters in a given stream. Used to create sub-streams
        """
        return {"authenticator": self.authenticator, "region": self.region}

class Projects(MixpanelStream):
    primary_key: str = "id"
    reqs_per_hour_limit = 0

    def path(self, **kwargs) -> str:
        return ''

    @property
    def url_base(self):
        return "https://mixpanel.com/api/app/me"

    def parse_response(self, response: requests.Response, **kwargs) -> Iterable[Mapping]:
        projects = response.json().get('results', {}).get('projects', {})
        for project_id, project_info in projects.items():
            project_info["id"] = project_id
            yield project_info

class ProjectSlicesMixin:
    def stream_slices(
        self, sync_mode, cursor_field: List[str] = None, stream_state: Mapping[str, Any] = None
    ) -> Iterable[Optional[Mapping[str, Any]]]:
        return self.projects if self.projects else [None]

    def request_params(
        self, stream_state: Mapping[str, Any], stream_slice: Mapping[str, any] = None, next_page_token: Mapping[str, Any] = None
    ) -> MutableMapping[str, Any]:
        if stream_slice and "project_id" in stream_slice:
            return {"project_id": stream_slice["project_id"]}
        else:
            return {}


class DateSlicesMixin(ProjectSlicesMixin):

    def date_slices(self, stream_state=None):
        date_slices: list = []

        # use the latest date between self.start_date and stream_state
        start_date = self.start_date
        if stream_state:
            # Remove time part from state because API accept 'from_date' param in date format only ('YYYY-MM-DD')
            # It also means that sync returns duplicated entries for the date from the state (date range is inclusive)
            stream_state_date = datetime.fromisoformat(stream_state["date"]).date()
            start_date = max(start_date, stream_state_date)

        # use the lowest date between start_date and self.end_date, otherwise API fails if start_date is in future
        start_date = min(start_date, self.end_date)

        # move start_date back <attribution_window> days to sync data since that time as well
        start_date = start_date - timedelta(days=self.attribution_window)

        while start_date <= self.end_date:
            end_date = start_date + timedelta(days=self.date_window_size - 1)  # -1 is needed because dates are inclusive
            date_slices.append(
                {
                    "start_date": str(start_date),
                    "end_date": str(min(end_date, self.end_date)),
                }
            )
            # add 1 additional day because date range is inclusive
            start_date = end_date + timedelta(days=1)

        return date_slices
    def stream_slices(
        self, sync_mode, cursor_field: List[str] = None, stream_state: Mapping[str, Any] = None
    ) -> Iterable[Optional[Mapping[str, Any]]]:

        project_slices = super().stream_slices(sync_mode=sync_mode, cursor_field=cursor_field, stream_state=stream_state)
        for date_slice in self.date_slices(stream_state=stream_state):
            for project_slice in project_slices:
                if project_slice:
                    date_slice.update(project_slice)
                yield date_slice

    def request_params(
        self, stream_state: Mapping[str, Any], stream_slice: Mapping[str, any] = None, next_page_token: Mapping[str, Any] = None
    ) -> MutableMapping[str, Any]:
        params = super().request_params(stream_state=stream_state, stream_slice=stream_slice, next_page_token=next_page_token)
        return {
            "from_date": stream_slice["start_date"],
            "to_date": stream_slice["end_date"],
            **params
        }


class IncrementalMixpanelStream(MixpanelStream, ABC):
    def get_updated_state(self, current_stream_state: MutableMapping[str, Any], latest_record: Mapping[str, Any]) -> Mapping[str, any]:
        current_stream_state = current_stream_state or {}
        current_stream_state: str = current_stream_state.get("date", str(self.start_date))
        latest_record_date: str = latest_record.get(self.cursor_field, str(self.start_date))
        return {"date": max(current_stream_state, latest_record_date)}
