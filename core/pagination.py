from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardResultsPagination(PageNumberPagination):
    page_size             = 20
    page_size_query_param = "page_size"
    max_page_size         = 100
    page_query_param      = "page"

    def get_paginated_response(self, data) -> Response:
        return Response({
            "status":       "ok",
            "count":        self.page.paginator.count,
            "total_pages":  self.page.paginator.num_pages,
            "current_page": self.page.number,
            "page_size":    self.get_page_size(self.request),
            "next":         self.get_next_link(),
            "previous":     self.get_previous_link(),
            "results":      data,
        })

    def get_paginated_response_schema(self, schema: dict) -> dict:
        return {
            "type":       "object",
            "required":   ["status", "count", "results"],
            "properties": {
                "status":       {"type": "string",  "example": "ok"},
                "count":        {"type": "integer", "example": 1234},
                "total_pages":  {"type": "integer", "example": 62},
                "current_page": {"type": "integer", "example": 2},
                "page_size":    {"type": "integer", "example": 20},
                "next":         {"type": "string",  "nullable": True, "format": "uri"},
                "previous":     {"type": "string",  "nullable": True, "format": "uri"},
                "results":      schema,
            },
        }


class LargeResultsPagination(StandardResultsPagination):
    page_size     = 100
    max_page_size = 1_000


class CompactResultsPagination(StandardResultsPagination):
    page_size     = 10
    max_page_size = 50
