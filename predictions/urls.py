from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views
from . import views 
from .views import forcar_atualizacao

# Rotas do app
urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.calendario, name='calendario'), 
    path('tabela/', views.classificacao, name='classificacao'),
    path('detalhes/<int:partida_id>/', views.detalhes_confronto, name='detalhes_confronto'),
    path('simulacao/', views.simulacao, name='simulacao'),
    path('atualizar-sistema/', forcar_atualizacao, name='atualizar_sistema'),
    path('votar/<int:partida_id>/', views.votar_partida, name='votar_partida'),
    path('time/<int:time_id>/', views.detalhes_time, name='detalhes_time'),
    path('exportar-calendario/', views.exportar_calendario, name='exportar_calendario'),
    path('login/', auth_views.LoginView.as_view(template_name='predictions/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('cadastro/', views.cadastro, name='cadastro'),
]