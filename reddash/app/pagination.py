import typing  # isort:skip

from markupsafe import Markup


class Pagination(list):
    """Pagination system for lists."""

    DEFAULT_PER_PAGE: int = 20
    DEFAULT_PAGE: int = 1

    def __init__(self, *args, **kwargs) -> None:
        self.total: int = kwargs.pop("total", None)
        self.per_page: int = kwargs.pop("per_page", None)
        self.pages: int = kwargs.pop("pages", None)
        self.page: int = kwargs.pop("page", None)
        self.default_per_page: int = kwargs.pop("default_per_page", self.DEFAULT_PER_PAGE)
        self.default_page: int = kwargs.pop("default_page", 1)
        super().__init__(*args, **kwargs)

    def to_dict(self) -> dict[str, typing.Any]:
        return {
            "items": list(self),
            "total": self.total,
            "per_page": self.per_page,
            "pages": self.pages,
            "page": self.page,
            "default_per_page": self.default_per_page,
            "default_page": self.default_page,
        }

    def __repr__(self) -> str:
        return f"<Pagination page={self.page} of {self.pages}>"

    def has_prev(self) -> bool:
        return self.page > 1

    def has_next(self) -> bool:
        return self.page < self.pages

    @property
    def elements_numbers(self) -> list[int]:
        return list(range(1, self.total + 1))

    @property
    def pages_numbers(self) -> list[int]:
        return list(range(1, self.pages + 1))

    @classmethod
    def from_list(
        cls,
        items: list[typing.Any],
        per_page: int | str | None = None,
        page: int | str | None = None,
        default_per_page: int = DEFAULT_PER_PAGE,
        default_page: int = DEFAULT_PAGE,
    ) -> typing.Any:
        per_page = (
            default_per_page
            if per_page is None
            else (
                int(per_page)
                if isinstance(per_page, str)
                and per_page.isdigit()
                and 1 <= int(per_page) <= max(default_per_page * 5, 100)
                else default_per_page
            )
        )
        page = (
            default_page
            if page is None
            else (
                int(page)
                if isinstance(page, str) and page.isdigit() and int(page) >= 1
                else default_page
            )
        )
        total = len(items)
        pages = (total // per_page) + (total % per_page > 0)
        page = min(page, pages)
        start = (page - 1) * per_page
        end = start + per_page
        return cls(
            items[start:end],
            total=total,
            per_page=per_page,
            pages=pages,
            page=page,
            default_per_page=default_per_page,
            default_page=default_page,
        )

    def to_html(
        self,
        KEY: str = "pagination",
        custom_kwargs: bool = False,
        render_template_string: bool = True,
    ) -> Markup:
        html = """<br />
        <div id="KEY-pagination"></div>
        <script>
            {% if KEY.has_prev() or KEY.has_next() %}
                document.addEventListener("DOMContentLoaded", function () {
                    {% if KEY.page|string != request.args.get("CUSTOM_KWARGpage", KEY.default_page|string) or KEY.per_page|string != request.args.get("CUSTOM_KWARGper_page", KEY.default_per_page|string) %}
                        window.history.pushState({}, "", '{{ url_for_query(CUSTOM_KWARGpage=KEY.page if KEY.page != KEY.default_page else None, CUSTOM_KWARGper_page=KEY.page if KEY.per_page != KEY.default_per_page else None) }}');
                    {% endif %}
                    var pagination = $("#KEY-pagination").pagination({
                        dataSource: {{ KEY.elements_numbers|tojson }},
                        pageSize: {{ KEY.per_page }},
                        pageNumber: {{ KEY.page }},
                        callback: function(data, pagination) {
                            if (pagination.pageNumber == {{ KEY.page }}) {
                                return;
                            }
                            if (pagination.pageNumber == {{ KEY.default_page }}) {
                                redirect_url = "{{ url_for_query(CUSTOM_KWARGpage=None) }}";
                            } else {
                                redirect_url = '{{ url_for_query(CUSTOM_KWARGpage="1234567890") }}'.replace("1234567890", pagination.pageNumber);
                            }
                            document.location.href = redirect_url.replace("amp;", "");
                        },
                        beforeSizeSelectorChange: function (event) {
                            var newPageSize = event.target.value;
                            if (newPageSize == {{ KEY.per_page }}) {
                                return;
                            }
                            if (newPageSize == {{ KEY.default_per_page }}) {
                                redirect_url = "{{ url_for_query(CUSTOM_KWARGpage=None, CUSTOM_KWARGper_page=None) }}";
                            } else {
                                redirect_url = '{{ url_for_query(CUSTOM_KWARGpage=None, CUSTOM_KWARGper_page="1234567890") }}'.replace("1234567890", newPageSize);
                            }
                            document.location.href = redirect_url.replace("amp;", "");
                        },
                        className: 'paginationjs-big paginationjs-theme-green',
                        showSizeChanger: true,
                        showGoInput: true,
                        showGoButton: true,
                        autoHidePrevious: true,
                        autoHideNext: true,
                        goButtonText: '{{ _("Go") }}',
                    })
                });
            {% endif %}
        </script>""".replace("KEY", KEY).replace("CUSTOM_KWARG", f"{KEY}_" if custom_kwargs else "")
        if not render_template_string:
            return html
        from flask import render_template_string

        return Markup(render_template_string(html, **{KEY: self}))
