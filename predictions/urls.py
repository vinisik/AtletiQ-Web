from django.urls import path
from . import views 
from .views import forcar_atualizacao

# Rotas do app
urlpatterns = [
    path('', views.calendario, name='calendario'), 
    path('tabela/', views.classificacao, name='classificacao'),
    path('detalhes/<int:partida_id>/', views.detalhes_confronto, name='detalhes_confronto'),
    path('simulacao/', views.simulacao, name='simulacao'),
    path('atualizar-sistema/', forcar_atualizacao, name='atualizar_sistema'),
    path('votar/<int:partida_id>/', views.votar_partida, name='votar_partida'),
    path('time/<int:time_id>/', views.detalhes_time, name='detalhes_time'),
    path('exportar-calendario/', views.exportar_calendario, name='exportar_calendario'),
]