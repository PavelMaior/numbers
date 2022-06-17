from django.shortcuts import render
from django.views.generic import ListView
from rest_framework.viewsets import ModelViewSet

from .models import Order
from .serializers import OrderModelSerializer


class OrderModelViewSet(ModelViewSet):
    queryset = Order.objects.all()
    serializer_class = OrderModelSerializer


# class OrdersListView(ListView):
#     model = Order
#     template_name = 'productsapp/products_list.html'
#     context_object_name = 'products'
#     paginate_by = 5
#
#     def get_queryset(self):
#         # queryset = super().get_queryset().prefetch_related('category').all()
#         if 'pk' in self.kwargs:
#             queryset = Products.on_site.filter(category__id=self.kwargs['pk']).prefetch_related('category').all()
#         else:
#             queryset = Products.on_site.prefetch_related('category').all()
#         return queryset