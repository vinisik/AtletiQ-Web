from django.urls import path
from . import views 
from .views import forcar_atualizacao

# Rotas do app
urlpatterns = [
    path('', views.calendario, name='calendario'), # Calendário agora é a Home
    path('tabela/', views.classificacao, name='classificacao'), # Tabela movida para /tabela/
    path('detalhes/<int:partida_id>/', views.detalhes_confronto, name='detalhes_confronto'),
    path('simulacao/', views.simulacao, name='simulacao'),
    path('atualizar-sistema/', forcar_atualizacao, name='atualizar_sistema'),
    path('votar/<int:partida_id>/', views.votar_partida, name='votar_partida'),
]