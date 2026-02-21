from django.db import models

class Time(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    escudo_url = models.URLField(blank=True, null=True)
    cor_hex = models.CharField(max_length=7, default="#FFFFFF")

    def __str__(self):
        return self.nome


class Liga(models.Model):
    nome = models.CharField(max_length=100)
    slug = models.SlugField(unique=True) 
    pais = models.CharField(max_length=50)

    def __str__(self):
        return self.nome


class Partida(models.Model):
    liga = models.ForeignKey(Liga, on_delete=models.CASCADE, null=True, blank=True)
    temporada = models.IntegerField(null=True, blank=True)
    rodada = models.IntegerField()
    data = models.DateTimeField()
    home_team = models.ForeignKey(Time, on_delete=models.CASCADE, related_name='jogos_casa')
    away_team = models.ForeignKey(Time, on_delete=models.CASCADE, related_name='jogos_fora')
    fthg = models.IntegerField(null=True, blank=True) # Gols Mandante
    ftag = models.IntegerField(null=True, blank=True) # Gols Visitante

    def __str__(self):
        return f"R{self.rodada}: {self.home_team} x {self.away_team}"
    

class Titulo(models.Model):
    time = models.ForeignKey(Time, on_delete=models.CASCADE, related_name='titulos')
    nome = models.CharField(max_length=100)  
    ano = models.CharField(max_length=4)    
    imagem = models.URLField(null=True, blank=True) 

    def __str__(self):
        return f"{self.nome} ({self.ano}) - {self.time.nome}"
    
class Artilheiro(models.Model):
    nome = models.CharField(max_length=100)
    time = models.CharField(max_length=100)
    gols = models.IntegerField()
    assistencias = models.IntegerField(default=0, null=True, blank=True)
    
    def __str__(self):
        return f"{self.nome} ({self.time}) - {self.gols} gols"

class VotoPopular(models.Model):
    partida = models.ForeignKey(Partida, on_delete=models.CASCADE, related_name='votos')
    escolha = models.CharField(max_length=1) 
    ip_address = models.GenericIPAddressField(null=True, blank=True) # Para evitar spam 

    def __str__(self):
        return f"Voto {self.escolha} no jogo {self.partida}"