import csv
from django.contrib.admin import SimpleListFilter
from django.contrib import admin
from django.urls import path
from django.http import HttpResponseRedirect, HttpResponse
from django.core.management import call_command
from django.contrib import messages
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from .models import Liga, Time, Partida, Titulo, VotoPopular

# Filtro Customizado
class LigaDoTimeFilter(SimpleListFilter):
    title = 'Liga' 
    parameter_name = 'liga' 

    def lookups(self, request, model_admin):
        ligas = Liga.objects.all().order_by('nome')
        return [(str(liga.pk), liga.nome) for liga in ligas]

    def queryset(self, request, queryset):
        if self.value():
            partidas = Partida.objects.filter(liga_id=self.value())
            
            home_ids = list(partidas.values_list('home_team_id', flat=True))
            away_ids = list(partidas.values_list('away_team_id', flat=True))
            
            ids_na_liga = set(home_ids + away_ids)
            
            return queryset.filter(id__in=ids_na_liga)
        return queryset

@admin.register(Liga)
class LigaAdmin(admin.ModelAdmin):
    list_display = ('nome', 'pais', 'slug', 'logo_preview')
    search_fields = ('nome', 'pais')

    # Preview da imagem da liga no Admin
    def logo_preview(self, obj):
        if obj.logo_url:
            return format_html('<img src="{}" style="max-height: 30px; max-width: 30px; object-fit: contain;" />', obj.logo_url)
        return "-"
    logo_preview.short_description = 'Logo'

@admin.register(Time)
class TimeAdmin(admin.ModelAdmin):
    list_display = ('nome', 'escudo_preview')
    search_fields = ('nome',)
    list_filter = (LigaDoTimeFilter,)

    # Preview do escudo do time no Admin
    def escudo_preview(self, obj):
        if obj.escudo_url:
            return format_html('<img src="{}" style="max-height: 30px; max-width: 30px; object-fit: contain;" />', obj.escudo_url)
        return "-"
    escudo_preview.short_description = 'Escudo'

@admin.register(Partida)
class PartidaAdmin(admin.ModelAdmin):
    list_display = ('data', 'status_badge', 'home_team', 'placar', 'away_team', 'liga', 'temporada', 'rodada')
    
    # Filtros 
    list_filter = ('liga', 'temporada', 'data')
    search_fields = ('home_team__nome', 'away_team__nome')
    
    # Navegação por datas no topo
    date_hierarchy = 'data'
    
    change_list_template = "admin/predictions/partida/change_list.html"
    
    # Registar a nova ação de exportação
    actions = ['exportar_para_csv']

    # Função para exibir o placar formatado
    def placar(self, obj):
        if obj.fthg is not None and obj.ftag is not None:
            return f"{int(obj.fthg)} x {int(obj.ftag)}"
        return "Agendado"
    placar.short_description = 'Placar'

    # Função para os Badges de Status 
    def status_badge(self, obj):
        if obj.fthg is not None:
            return mark_safe('<span style="background: #00E676; color: black; padding: 4px 10px; border-radius: 12px; font-weight: bold; font-size: 11px; text-transform: uppercase;">Encerrado</span>')
        return mark_safe('<span style="background: #333; color: white; padding: 4px 10px; border-radius: 12px; font-weight: bold; font-size: 11px; text-transform: uppercase;">Agendado</span>')
    status_badge.short_description = 'Status'

    # Lógica da ação de exportação para CSV
    @admin.action(description='Exportar partidas selecionadas para CSV')
    def exportar_para_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="dataset_partidas.csv"'
        
        writer = csv.writer(response)
        # Cabeçalho do CSV
        writer.writerow(['Data', 'Liga', 'Mandante', 'Visitante', 'Gols_Mandante', 'Gols_Visitante', 'Odd_Casa', 'Odd_Empate', 'Odd_Fora'])
        
        # Inserção de Dados
        for jogo in queryset:
            writer.writerow([
                jogo.data.strftime('%Y-%m-%d %H:%M') if jogo.data else '',
                jogo.liga.nome if jogo.liga else '',
                jogo.home_team.nome,
                jogo.away_team.nome,
                jogo.fthg,
                jogo.ftag,
                jogo.odd_h,
                jogo.odd_d,
                jogo.odd_a
            ])
        return response

    # Rota para o botão de sincronização
    def get_urls(self):
        urls = super().get_urls()
        my_urls = [
            path('sincronizar-api/', self.admin_site.admin_view(self.sincronizar_api), name='sincronizar_api_partidas'),
        ]
        return my_urls + urls

    def sincronizar_api(self, request):
        try:
            call_command('sync_data')
            self.message_user(
                request, 
                "Sincronização concluída com sucesso! Todos os jogos e Odds foram atualizados.", 
                level=messages.SUCCESS
            )
        except Exception as e:
            self.message_user(
                request, 
                f"Erro ao sincronizar: {e}", 
                level=messages.ERROR
            )
            
        return HttpResponseRedirect("../")

@admin.register(Titulo)
class TituloAdmin(admin.ModelAdmin):
    list_display = ('time', 'nome', 'ano')
    search_fields = ('time__nome', 'nome')
    list_filter = ('time',)

@admin.register(VotoPopular)
class VotoPopularAdmin(admin.ModelAdmin):
    list_display = ('partida', 'escolha')
    list_filter = ('escolha',)