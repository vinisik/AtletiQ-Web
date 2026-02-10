import pandas as pd
import logging
import json
import os
from django.conf import settings
from django.db import models
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from .ai_logic.web_scraper import AtletiQScraper
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import VotoPopular, Partida
from .models import Time, Partida, Titulo
from django.db.models import Q, F, Sum, Max
from .ai_logic.predictor import prever_jogo_especifico, simular_campeonato
from .ai_logic.feature_engineering import preparar_dados_para_modelo
from .ai_logic.model_trainer import treinar_modelo, carregar_ia, salvar_ia
from .ai_logic.analysis import gerar_confronto_direto
from django.core.management import call_command

logger = logging.getLogger('predictions')

def carregar_escudos_json():
    """Lê o dicionário de escudos do arquivo escudos.json na raiz do projeto."""
    caminho_json = os.path.join(settings.BASE_DIR, 'escudos.json')
    try:
        with open(caminho_json, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Erro ao carregar escudos.json: {e}")
        return {}

def obter_contexto_ia():
    """
    Treina um modelo 'on-the-fly' com os dados atuais do banco.
    Útil para fallback ou predições detalhadas de um jogo específico.
    """
    partidas_query = Partida.objects.filter(fthg__isnull=False).values(
        'data', 'home_team__nome', 'away_team__nome', 'fthg', 'ftag', 'rodada'
    )
    
    # Se não houver jogos suficientes, retorna None
    if not partidas_query: 
        return None, None, None, None

    df_res = pd.DataFrame(list(partidas_query))
    df_res.columns = ['Date', 'HomeTeam', 'AwayTeam', 'FTHG', 'FTAG', 'Rodada']
    
    # Prepara dados 
    df_treino, time_stats = preparar_dados_para_modelo(df_res)
    
    # Treina o modelo 
    modelos, encoder, cols_model = treinar_modelo(df_treino)
    
    return modelos, encoder, time_stats, cols_model


def classificacao(request):
    """Gera a tabela oficial de 2026 com estatísticas completas."""
    times_ids_2026 = Partida.objects.filter(data__year=2026).values_list('home_team_id', flat=True).distinct()
    times = Time.objects.filter(id__in=times_ids_2026)
    tabela = []
    escudos = carregar_escudos_json()

    for time in times:
        jogos_casa = Partida.objects.filter(home_team=time, data__year=2026, fthg__isnull=False)
        jogos_fora = Partida.objects.filter(away_team=time, data__year=2026, fthg__isnull=False)

        v_casa = jogos_casa.filter(fthg__gt=F('ftag')).count()
        v_fora = jogos_fora.filter(ftag__gt=F('fthg')).count()
        vitorias = v_casa + v_fora

        e_casa = jogos_casa.filter(fthg=F('ftag')).count()
        e_fora = jogos_fora.filter(ftag=F('fthg')).count()
        empates = e_casa + e_fora

        d_casa = jogos_casa.filter(fthg__lt=F('ftag')).count()
        d_fora = jogos_fora.filter(ftag__lt=F('fthg')).count()
        derrotas = d_casa + d_fora

        gm_casa = jogos_casa.aggregate(Sum('fthg'))['fthg__sum'] or 0
        gm_fora = jogos_fora.aggregate(Sum('ftag'))['ftag__sum'] or 0
        gs_casa = jogos_casa.aggregate(Sum('ftag'))['ftag__sum'] or 0
        gs_fora = jogos_fora.aggregate(Sum('fthg'))['fthg__sum'] or 0

        gm = gm_casa + gm_fora
        gs = gs_casa + gs_fora
        sg = gm - gs
        pontos = (vitorias * 3) + empates
        total_jogos = jogos_casa.count() + jogos_fora.count()

        ultimos = obter_ultimos_jogos(time.nome)

        tabela.append({
            'nome': time.nome,
            'p': pontos,
            'j': total_jogos,
            'v': vitorias,
            'e': empates,
            'd': derrotas,
            'gm': gm,
            'gs': gs,
            'sg': sg,
            'ultimos': ultimos
        })

    tabela = sorted(tabela, key=lambda x: (-x['p'], -x['v'], -x['sg'], -x['gm']))

    return render(request, 'predictions/tabela.html', {
        'tabela': tabela, 
        'ESCUDOS': escudos
    })

def calendario(request):
    # Determina qual rodada exibir
    rodada_param = request.GET.get('rodada')
    
    # Descobre a última rodada cadastrada no banco 
    max_rodada = Partida.objects.filter(data__year=2026).aggregate(m=Max('rodada'))['m'] or 38

    if rodada_param:
        try:
            rodada_atual = int(rodada_param)
        except ValueError:
            rodada_atual = 1
    else:
        # Se não escolher rodada pega a primeira que tem jogos não realizados 
        # Se o campeonato acabou, mostra a última.
        proximo_jogo = Partida.objects.filter(data__year=2026, fthg__isnull=True).order_by('rodada').first()
        rodada_atual = proximo_jogo.rodada if proximo_jogo else max_rodada

    #Filtra os jogos APENAS dessa rodada
    jogos = Partida.objects.filter(
        data__year=2026, 
        rodada=rodada_atual
    ).order_by('data')

    # Define os botões de navegação
    rodada_anterior = rodada_atual - 1 if rodada_atual > 1 else None
    rodada_proxima = rodada_atual + 1 if rodada_atual < max_rodada else None

    escudos = carregar_escudos_json()
    
    return render(request, 'predictions/calendario.html', {
        'jogos': jogos, 
        'ESCUDOS': escudos,
        'rodada_atual': rodada_atual,
        'anterior': rodada_anterior,
        'proxima': rodada_proxima
    })


def simulacao(request):
    """Executa a simulação estocástica para o campeonato."""
    try:
        escudos = carregar_escudos_json()
        
        # Tenta carregar IA do cache
        modelos_dict, encoder, colunas, time_stats = carregar_ia()
        
        # Se não existir cache, treina agora 
        if modelos_dict is None or time_stats is None:
            logger.warning("Cache de IA não encontrado. Treinando novo modelo...")
            modelos_dict, encoder, time_stats, colunas = obter_contexto_ia()
            
            # Se ainda falhar retorna erro
            if modelos_dict is None:
                return render(request, 'predictions/simulacao.html', {
                    'error': 'Dados insuficientes para treinar a IA (Mínimo 20 jogos).'
                })
            
            # Salva para ser mais rápido
            salvar_ia(modelos_dict, encoder, colunas, time_stats)

        # Prepara dados para simulação
        realizados_qs = Partida.objects.filter(data__year=2026, fthg__isnull=False)
        futuros_qs = Partida.objects.filter(data__year=2026, fthg__isnull=True)

        if not futuros_qs.exists():
            return render(request, 'predictions/simulacao.html', {'error': 'Campeonato finalizado.'})

        df_res = pd.DataFrame(list(realizados_qs.values('home_team__nome', 'away_team__nome', 'fthg', 'ftag')))
        df_res.columns = ['HomeTeam', 'AwayTeam', 'FTHG', 'FTAG']
        
        df_fut = pd.DataFrame(list(futuros_qs.values('home_team__nome', 'away_team__nome', 'rodada')))
        df_fut.columns = ['HomeTeam', 'AwayTeam', 'Rodada']

        # Executa simulação
        res_df = simular_campeonato(38, df_fut, df_res, modelos_dict, encoder, time_stats, colunas)
        
        # Limpeza de nomes
        res_df['Time'] = res_df['Time'].astype(str).str.replace(r'^\d+\s+', '', regex=True).str.strip()
        
        tabela_simulada = res_df.to_dict('records')
        
        return render(request, 'predictions/simulacao.html', {
            'tabela': tabela_simulada,
            'ESCUDOS': escudos
        })

    except Exception as e:
        logger.exception("Falha na execução da simulação")
        return render(request, 'predictions/simulacao.html', {'error': f"Erro técnico na simulação: {str(e)}"})

def detalhes_confronto(request, partida_id):
    try:
        partida = get_object_or_404(Partida, pk=partida_id)
        
        # Busca Histórico (H2H) 
        h2h = Partida.objects.filter(
            home_team=partida.home_team, 
            away_team=partida.away_team,
            fthg__isnull=False
        ).exclude(pk=partida.pk).order_by('-data')[:5]
        
        h2h_lista = []
        for p in h2h:
            h2h_lista.append({
                'Data': p.data.isoformat() if p.data else None,
                'Mandante': p.home_team.nome,
                'Visitante': p.away_team.nome,
                'GM': p.fthg,
                'GV': p.ftag
            })

        # IA e Previsão
        probs = {'Casa': 0.33, 'Empate': 0.33, 'Visitante': 0.33} # Padrão de segurança
        try:
            dados_ia = carregar_ia() 
            # Verifica se carregou tudo corretamente 
            if dados_ia and len(dados_ia) == 4:
                modelos, encoder, colunas, time_stats = dados_ia
                resultado_ia = prever_jogo_especifico(
                    partida.home_team.nome, 
                    partida.away_team.nome, 
                    modelos, encoder, time_stats, colunas
                )
                if resultado_ia:
                    probs = resultado_ia
        except Exception as e:
            print(f"Aviso: IA indisponível para o jogo {partida}. Erro: {e}")

        # Forma Recente 
        def get_ultimos(time):
            jogos = Partida.objects.filter(
                models.Q(home_team=time) | models.Q(away_team=time),
                fthg__isnull=False,
                data__year=2026 
            ).order_by('-data')[:5]
            
            res = []
            for j in jogos:
                if j.fthg is None or j.ftag is None:
                    continue

                g_pro = j.fthg if j.home_team == time else j.ftag
                g_con = j.ftag if j.home_team == time else j.fthg
                
                if g_pro > g_con: res.append('V')
                elif g_pro == g_con: res.append('E')
                else: res.append('D')
            return res

        # Resposta JSON 
        data = {
            'id': partida.pk,
            'home': partida.home_team.nome,
            'away': partida.away_team.nome,
            'home_id': partida.home_team.pk,   
            'away_id': partida.away_team.pk,
            'encerrado': partida.fthg is not None,
            'placar_home': partida.fthg,
            'placar_away': partida.ftag,
            'prob_casa': probs.get('Casa', 0.33),
            'prob_empate': probs.get('Empate', 0.33),
            'prob_visitante': probs.get('Visitante', 0.33),
            'forma_home': get_ultimos(partida.home_team),
            'forma_away': get_ultimos(partida.away_team),
            'h2h_lista': h2h_lista
        }
        
        return JsonResponse(data)
        
    except Exception as e:
        print(f"Erro CRÍTICO no detalhes_confronto: {e}")
        return JsonResponse({'error': str(e)}, status=500)

def detalhes_time(request, time_id):
    time_obj = get_object_or_404(Time, pk=time_id)
    escudos = carregar_escudos_json()
    
    # Histórico Recente
    jogos = Partida.objects.filter(
        (Q(home_team=time_obj) | Q(away_team=time_obj)),
        fthg__isnull=False, 
        ftag__isnull=False,  
        data__year=2026
    ).order_by('-data')
    
    historico = []
    for j in jogos:
        if j.fthg is None or j.ftag is None:
            continue

        res = 'E'
        if j.fthg != j.ftag:
            venceu = (j.home_team == time_obj and j.fthg > j.ftag) or \
                     (j.away_team == time_obj and j.ftag > j.fthg)
            res = 'V' if venceu else 'D'
        
        adv = j.away_team if j.home_team == time_obj else j.home_team
        historico.append({
            'jogo': j, 
            'resultado': res, 
            'adversario': adv, 
            'placar': f"{int(j.fthg)} x {int(j.ftag)}",
            'mando': 'C' if j.home_team == time_obj else 'F'
        })

    # Gráfico Evolução 
    ev_labels, ev_data = [], []
    all_games = Partida.objects.filter(
        data__year=2026, 
        fthg__isnull=False, 
        ftag__isnull=False
    ).order_by('rodada')
    
    df = pd.DataFrame(list(all_games.values('rodada', 'home_team_id', 'away_team_id', 'fthg', 'ftag')))
    
    if not df.empty:
        for r in range(1, int(df['rodada'].max()) + 1):
            sub = df[df['rodada'] <= r]
            pts = {}
            # Inicializa todos
            all_ids = set(df['home_team_id']).union(set(df['away_team_id']))
            for t in all_ids: pts[t] = 0
            
            for _, row in sub.iterrows():
                if pd.isna(row['fthg']) or pd.isna(row['ftag']):
                    continue
                    
                h, a = row['home_team_id'], row['away_team_id']
                hg, ag = row['fthg'], row['ftag']
                
                if hg > ag: pts[h] += 3
                elif ag > hg: pts[a] += 3
                else: pts[h]+=1; pts[a]+=1
            
            rank = sorted(pts.items(), key=lambda x: x[1], reverse=True)
            pos = next((i+1 for i, (tid, _) in enumerate(rank) if tid == time_obj.pk), None)
            if pos:
                ev_labels.append(f"R{r}")
                ev_data.append(pos)

    try:
        titulos_reais = Titulo.objects.filter(time=time_obj)
    except:
        titulos_reais = []

    return render(request, 'predictions/time.html', {
        'time': time_obj, 
        'escudo': escudos.get(time_obj.nome, ''), 
        'historico': historico,
        'evolucao_labels': json.dumps(ev_labels), 
        'evolucao_data': json.dumps(ev_data),
        'titulos': titulos_reais 
    })


def obter_ultimos_jogos(time_nome):
    """Retorna os últimos 5 resultados (V, E, D) de um time em 2026."""
    jogos = Partida.objects.filter(
        (Q(home_team__nome=time_nome) | Q(away_team__nome=time_nome)),
        fthg__isnull=False,
        ftag__isnull=False,
        data__year=2026
    ).order_by('-data')[:5]

    ultimos = []
    for jogo in jogos:
        if jogo.fthg is None or jogo.ftag is None:
            continue
            
        if jogo.fthg == jogo.ftag:
            ultimos.append('E')
        elif (jogo.home_team.nome == time_nome and jogo.fthg > jogo.ftag) or \
             (jogo.away_team.nome == time_nome and jogo.ftag > jogo.fthg):
            ultimos.append('V')
        else:
            ultimos.append('D')
            
    return ultimos[::-1]


def forcar_atualizacao(request):
    """
    Aciona o comando de sincronização sync_data através do botão no header.
    """
    try:
        # Chama o comando sync_data 
        print("Iniciando sincronização via botão...")
        call_command('sync_data')
        
        # Após sincronizar os dados, atualiza a IA
        modelos_dict, encoder, time_stats, colunas = obter_contexto_ia()
        
        if modelos_dict:
            salvar_ia(modelos_dict, encoder, colunas, time_stats)
            messages.success(request, "Sistema sincronizado com sucesso! (Dados + IA)")
        else:
            messages.warning(request, "Dados sincronizados, mas IA não treinada (poucos jogos).")

    except Exception as e:
        logger.error(f"Erro na atualização via botão: {e}")
        messages.error(request, f"Erro ao executar sync_data: {str(e)}")
    
    return redirect('calendario')


@csrf_exempt
def votar_partida(request, partida_id):
    if request.method == 'POST':
        data = json.loads(request.body)
        escolha = data.get('escolha') 
        
        if escolha in ['H', 'D', 'A']:
            VotoPopular.objects.create(partida_id=partida_id, escolha=escolha)
            
            # Recalcula porcentagens
            total = VotoPopular.objects.filter(partida_id=partida_id).count()
            h = VotoPopular.objects.filter(partida_id=partida_id, escolha='H').count()
            d = VotoPopular.objects.filter(partida_id=partida_id, escolha='D').count()
            a = VotoPopular.objects.filter(partida_id=partida_id, escolha='A').count()
            
            return JsonResponse({
                'total': total,
                'H': int((h/total)*100),
                'D': int((d/total)*100),
                'A': int((a/total)*100)
            })
    return JsonResponse({'error': 'Invalid request'}, status=400)