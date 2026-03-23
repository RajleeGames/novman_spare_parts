from django.urls import path
from . import views

app_name = "agrovet"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("sales/", views.sale_list, name="sale_list"),
    path("sales/add/", views.sale_create, name="sale_create"),
    path("sales/<int:pk>/", views.sale_detail, name="sale_detail"),
    path("sales/<int:pk>/payment/", views.add_payment, name="add_payment"),

    path("expenses/", views.expense_list, name="expense_list"),
    path("expenses/add/", views.expense_create, name="expense_create"),

    path("customers/", views.customer_list, name="customer_list"),
]