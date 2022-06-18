from django.shortcuts import render
from django.views.generic import ListView
from rest_framework.viewsets import ModelViewSet

from .models import Order
from .serializers import OrderModelSerializer


class OrderModelViewSet(ModelViewSet):
    queryset = Order.objects.all()
    serializer_class = OrderModelSerializer


class OrdersListView(ListView):

    model = Order
    template_name = 'ordersapp/orders_list.html'
    context_object_name = 'orders'
    paginate_by = 10
    ordering = ['id']

