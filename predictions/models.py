from django.db import models

class Time(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    escudo_url = models.URLField(blank=True, null=True)
    cor_hex = models.CharField(max_length=7, default="#FFFFFF")

    def __str__(self):
        return self.nome

class Partida(models.Model):
    rodada = models.IntegerField()
    data = models.DateTimeField()
    home_team = models.ForeignKey(Time, on_delete=models.CASCADE, related_name='jogos_casa')
    away_team = models.ForeignKey(Time, on_delete=models.CASCADE, related_name='jogos_fora')
    fthg = models.IntegerField(null=True, blank=True) # Gols Mandante
    ftag = models.IntegerField(null=True, blank=True) # Gols Visitante

    def __str__(self):
        return f"R{self.rodada}: {self.home_team} x {self.away_team}"