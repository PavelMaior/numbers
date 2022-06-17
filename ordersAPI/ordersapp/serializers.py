from rest_framework.serializers import HyperlinkedModelSerializer
from .models import Order


class OrderModelSerializer(HyperlinkedModelSerializer):
    class Meta:
        model = Order
        fields = ('id', 'usd_price', 'rub_price', 'delivery_date')
