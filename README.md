# Simulador de Rede de Filas - T1

## Requisitos
- Python 3.7+
- PyYAML: `pip install pyyaml`

## Como executar o simulator nosso e o java fornecido pra comparar resultados

```bash
python Simulator.py run <arquivo_modelo.yml>
```

java -jar simulator.jar run model.yml

**Exemplo com o modelo do módulo 3:**
```bash
python simulator.py run model.yml
```

**Exemplo com o modelo do T1:**
```bash
python simulator.py run model_t1.yml
```

---

## Saída do simulador

Para cada fila, o relatório exibe:
- **Estado**: número de clientes presentes (em serviço + esperando)
- **Tempo**: tempo acumulado naquele estado (média das simulações)
- **Probabilidade**: percentual do tempo total gasto naquele estado
- **Perdas**: clientes perdidos por capacidade cheia
- **Tempo global**: tempo total médio da simulação

---

## Modelo do T1 (enunciado)

Topologia simulada conforme o diagrama:

```
Chegada externa (2..4min) → Q1 (G/G/1, serviço 1..2min)
   Q1 → Q2 com prob 0.8
   Q1 → Q3 com prob 0.2

Q2 (G/G/2/5, serviço 4..6min):
   Q2 → Q1 com prob 0.5  (retroalimentação)
   Q2 → Q3 com prob 0.3
   Q2 → exterior com prob 0.2

Q3 (G/G/2/10, serviço 5..15min):
   Q3 → Q1 com prob 0.7  (retroalimentação)
   Q3 → exterior com prob 0.3
```

Simulação: 5 seeds, 100.000 números aleatórios cada.
