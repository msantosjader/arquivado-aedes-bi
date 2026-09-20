## Pipeline COMPESA

O pipeline salva o retorno bruto em `JSONL.gz`, trata os períodos e serviços e gera indicadores mensais para Recife.

```bash
uv sync
uv run python pipeline.py --ano 2026
uv run python mapa_areas.py
```

Saídas principais:

- `data/raw/compesa/`: cache bruto da API;
- `data/curated/`: períodos e serviços padronizados;
- `data/analytics/mensal/`: indicadores mensais em Parquet;
- `data/mapa_recife.html`: mapa com slider mensal e seletor de ano.

O mapa usa todos os anos disponíveis por padrão. Para limitar o intervalo:

```bash
uv run python mapa_areas.py --ano-inicio 2024 --ano-fim 2026
```

Use `--refresh` apenas para criar um novo snapshot da API.

### Indicadores

`percentual_abastecimento_calendario` é calculado pela união dos intervalos do calendário (`layer 5`) dentro do mês, dividida pelo total de horas do mês. Intervalos sobrepostos não são contados duas vezes.

O mapa exibe o abastecimento estimado do município para o mês selecionado, ponderado pela quantidade de economias cadastradas:

```text
abastecimento estimado = soma(percentual × economias cadastradas)
                         / soma(economias cadastradas)
```

A média simples das áreas é mantida apenas como referência técnica, pois dá o mesmo peso a uma área pequena e a uma área com milhares de economias. A média ponderada caracteriza melhor o abastecimento municipal considerando as unidades consumidoras cadastradas.

`Quantidade_de_Economias` é uma unidade cadastral da COMPESA. Não representa população. `Quantidade_de_Matriculas`, `Ligações_Residenciais` e `Ligações_Ligadas` são preservadas como variáveis auxiliares.

Quando uma área cruza o limite do Recife, a média ponderada usa `economias cadastradas × FRAC_AREA_RECIFE` como aproximação. Essa fração assume distribuição uniforme e não substitui uma localização real das economias.

Intervenções (`layer 2`) são mostradas no popup como eventos previstos no mês. Elas não são subtraídas automaticamente do percentual do calendário.

O popup também classifica os dias do mês: abastecimento integral (24 horas), abastecimento parcial (mais de 0 e menos de 24 horas) e sem abastecimento (0 horas). Esses três grupos são exclusivos e somam todos os dias do mês. Manutenção programada é exibida separadamente porque pode coincidir com qualquer uma das outras situações.
