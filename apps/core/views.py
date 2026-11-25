from django.http import JsonResponse


def not_found(request, exception=None):
    """Вместо HTML-страницы Django 404 отдаём JSON: клиент у нас — Postman/фронтенд."""
    return JsonResponse({'detail': 'Ресурс не найден.'}, status=404)


def server_error(request):
    """То же для 500. Подробности ошибки наружу не отдаём — они только в логах сервера."""
    return JsonResponse({'detail': 'Внутренняя ошибка сервера.'}, status=500)
