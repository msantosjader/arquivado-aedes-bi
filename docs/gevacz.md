# Dados GEVACZ

## Objetivo

Organizar as bases de estações disseminadoras (EDLs) e ovitrampas para
visualização e análise espacial junto com abastecimento, chuva e temperatura.
Os arquivos originais permanecem em `data/informacoes-gevacz/` e não são
alterados pelo pipeline.

## Entidades normalizadas

`gevacz.py` gera tabelas em `data/curated/gevacz/`:

- `edls.parquet`: um registro por ponto estratégico de EDL;
- `ovitrampas.parquet`: um registro por ovitrampa georreferenciada;
- `observacoes_ovitrampas.parquet`: um registro por ovitrampa e ciclo.
- `ciclos.parquet`: datas de início, fim e referência de cada ciclo;
- `observacoes_analiticas.parquet`: observações com contexto climático e de
  abastecimento nas janelas anteriores de 7, 14, 21 e 28 dias.
- `auditoria_coordenadas_ovitrampas.parquet`: pontos fora do Recife, sem área
  COMPESA ou sem coordenada válida.
- `auditoria_ids_ovitrampas.parquet`: IDs históricos sem correspondência
  geográfica e situação de cada ID.

Todas as tabelas preservam `arquivo_origem`. As observações preservam também
`aba_origem`.

## Campos principais

EDLs: `edl_id`, `distrito_sanitario`, `bairro`, `nome_local`, `tipo_local`,
`logradouro`, `latitude`, `longitude`, `edl_ideal` e `edl_real`.

Ovitrampas: `id_ovt`, `bairro`, `latitude`, `longitude`, `endereco` e
`id_ovt_chave`, `qualidade_coordenada` e `qualidade_geografica`.

`id_ovt_chave` remove espaços e pontuação para relacionar, por exemplo,
`BVS 1015` na localização com `BVS1015` nas observações. O ID original é
preservado para exibição.

Observações: `id_ovt`, `ano`, `ciclo`, `data_coleta`, `data_leitura`,
`quantidade_palhetas`, `n_ovos` e `status`.

O ano de origem e o ano da data são mantidos separadamente. Datas fora do ano
do arquivo são comparadas com os registros vizinhos e classificadas em
`qualidade_data`; elas não são corrigidas silenciosamente.

## Ciclos e janelas ambientais

O mapa usa `ano + ciclo` como linha do tempo. A data de referência do ciclo é a
mediana das datas de coleta válidas. Pontos físicos de ovitrampa são exibidos
independentemente da existência de uma observação no ciclo selecionado.

O segundo controle do mapa seleciona a janela anterior à coleta:

- 7 dias;
- 14 dias;
- 21 dias;
- 28 dias.

O dia da coleta não entra na janela. Para chuva são calculados acumulados; para
temperatura, médias; para abastecimento, horas e dias sem abastecimento.

Os arquivos 2024 e 2025 possuem ciclos sem data de coleta válida. Eles ficam
na tabela normalizada, mas não entram na linha do tempo do mapa até validação.

## Cobertura espacial provisória

O mapa permite selecionar um raio de 0 a 500 m para a área operacional
presumida, com 400 m como valor padrão. Esse valor é informado por material
da Fiocruz que relata disseminação efetiva até 400 m em ensaios realizados em
Manaus e Manacapuru (Abad-Franch et al., 2015; 2017). Isso não comprova
eficácia local no Recife.

As sensibilidades analíticas iniciais são 50, 100, 150, 200, 300, 400 e 500 m.

O raio de voo não é automaticamente o raio de eficácia de uma EDL. A eficácia
depende do tipo de estação, produto, manutenção, densidade e comportamento dos
mosquitos. Até existir protocolo ou evidência local da GEVACZ, o mapa e a
análise devem chamar esses buffers de `área operacional presumida`, nunca de
área de eficácia comprovada.

Referências de dispersão que orientam a hipótese, sem substituir validação
local:

- Trpis, M.; Hausermann, W. (1986). *Dispersal and other population parameters
  of Aedes aegypti in an African village*. American Journal of Tropical
  Medicine and Hygiene, 35(6), 1263-1279.
- Harrington, L. C. et al. (2005). *Dispersal of the dengue vector Aedes
  aegypti within and between rural communities*. American Journal of Tropical
  Medicine and Hygiene, 72(2), 209-220.

## Limitações conhecidas

- As planilhas de 2024 e 2025 têm formatos mistos e parte dos consolidados está
  agregada por bairro e ciclo.
- 2024 e 2025 usam formato largo, com blocos de três colunas por ciclo; 2026
  usa formato longo, com uma aba por ciclo.
- A consolidação atual encontrou 58.032 observações em 2024, 58.500 em 2025 e
  31.455 em 2026. Os números devem ser conferidos com a GEVACZ antes de análise
  substantiva.
- A base atual não documenta de forma suficiente a data de instalação,
  ativação, manutenção ou retirada de cada EDL.
- Há coordenadas em formatos inconsistentes, inclusive valores sem separador
  decimal e registros ausentes. O normalizador marca a qualidade, recupera
  apenas formatos numéricos não ambíguos e não corrige silenciosamente a
  origem.
- Pontos fora do limite municipal ou sem interseção com as áreas operacionais
  são retirados da camada do mapa e preservados na auditoria. Isso evita
  interpretar pontos no mar ou coordenadas deslocadas como cobertura real.
- Sem histórico operacional das EDLs, a comparação entre ovitrampas próximas e
  distantes é associação espacial, não avaliação causal ou antes/depois.
- A data de coleta é a referência temporal preferencial da ovitrampa. Quando
  ela estiver ausente, não se deve inventar uma data a partir da digitação.
- Os indicadores diários de abastecimento de 2024 e 2025 não possuem serviços
  registrados na extração atual; as respectivas janelas podem ficar sem esse
  componente até a fonte ser confirmada.

## Confirmações solicitadas à GEVACZ

- Qual é o significado exato de `QT` nas planilhas de ovitrampas?
- `N_OVOS` é contagem bruta e comparável entre anos e ciclos?
- Qual é a regra para quantidade de palhetas e ciclos incompletos?
- Os IDs das ovitrampas permanecem estáveis entre os anos?
- Qual produto e qual tipo de EDL são utilizados?
- Existe raio operacional ou área de influência validada para a EDL?
- Quais são as datas de instalação, manutenção, inatividade e retirada?
- `EDL ideal` e `EDL real` representam unidades físicas, pontos ou outra
  medida?
- As coordenadas atuais representam a operação durante todos os ciclos?

## Execução

```bash
uv run python pipeline.py --ano 2024
uv run python pipeline.py --ano 2025
uv run python pipeline.py --ano 2026
uv run python gevacz.py
uv run python mapa_areas.py --ano-inicio 2024 --ano-fim 2026
```
