from rest_framework.pagination import PageNumberPagination


class DefaultPagination(PageNumberPagination):
    """Один класс пагинации на весь API: ?page=2&page_size=20.

    Без пагинации GET /listings/ при 100 000 объявлений вернул бы всё сразу:
    медленно для сервера, БД и клиента. Максимум 100 защищает от ?page_size=10000000.
    """

    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100
