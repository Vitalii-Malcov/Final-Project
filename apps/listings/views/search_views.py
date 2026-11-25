from django.db.models import Count
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.listings.models import SearchQuery
from apps.listings.serializers import (
    PopularLimitSerializer,
    PopularSearchSerializer,
    SearchQuerySerializer,
)


class PopularSearchesView(APIView):
    """GET listings/searches/popular/?limit=10 — самые частые поисковые слова."""

    permission_classes = [AllowAny]  # публично

    def get(self, request):
        params = PopularLimitSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)

        # SELECT keyword, COUNT(id) FROM search_history GROUP BY keyword ORDER BY count DESC.
        # values('keyword') ДО annotate() задаёт GROUP BY. order_by() обязателен: у модели есть
        # ordering = ['-created_at'], и без явной сортировки created_at попал бы в GROUP BY,
        # группы разъехались бы по каждой строке и счётчики всегда были бы равны 1.
        queryset = (
            SearchQuery.objects.values('keyword')
            .annotate(count=Count('id'))
            .order_by('-count', 'keyword')[:params.validated_data['limit']]
        )
        return Response(PopularSearchSerializer(queryset, many=True).data)


class MySearchesView(ListAPIView):
    """GET listings/searches/my/ — история поиска текущего пользователя (новые первыми)."""

    permission_classes = [IsAuthenticated]
    serializer_class = SearchQuerySerializer

    def get_queryset(self):
        return SearchQuery.objects.filter(user=self.request.user)
