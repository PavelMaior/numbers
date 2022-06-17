from django.db import models


class Order(models.Model):
    id = models.BigIntegerField(primary_key=True)
    usd_price = models.IntegerField()
    rub_price = models.DecimalField(max_digits=11, decimal_places=2)
    delivery_date = models.DateField()
