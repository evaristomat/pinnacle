# 📊 Sistema de Processamento de Dados Históricos de LoL

Sistema melhorado para baixar, processar e organizar dados históricos de jogos de League of Legends para análise de apostas.

## 🚀 Início Rápido

### Instalação

```bash
# Instalar dependências
pip install -r requirements.txt
```

### Uso Básico

```bash
# Executar pipeline completo (download → clean → ligas)
python main.py
```

## 📁 Estrutura

```
database_improved/
├── config.py              # Configurações centralizadas
├── download.py             # Download do CSV do Google Drive
├── clean_database.py       # Processamento e limpeza de dados
├── ligas.py                # Geração de mapeamento liga → times
├── main.py                 # Pipeline completo (orquestrador)
├── database_schema.py       # Schema SQLite (opcional)
├── requirements.txt        # Dependências Python
└── README.md              # Esta documentação
```

## 🔄 Fluxo de Trabalho

```
1. download.py
   ↓
   database.csv (dados brutos do Google Drive)
   
2. clean_database.py
   ↓
   data_transformed.csv (dados limpos, formato matchup)
   
3. ligas.py
   ↓
   ligas_times.json (mapeamento liga → times)
```

## 📝 Uso Detalhado

### Pipeline Completo

```bash
python main.py
```

Executa todas as etapas em sequência:
1. **Download**: Baixa `database.csv` do Google Drive
2. **Limpeza**: Processa e transforma dados
3. **Ligas**: Gera mapeamento de times por liga

### Etapas Individuais

```bash
# Apenas download
python main.py --download-only

# Apenas limpeza (requer database.csv existente)
python main.py --clean-only

# Apenas geração de ligas (requer data_transformed.csv existente)
python main.py --ligas-only

# Pula download (usa CSV existente)
python main.py --skip-download
```

### Scripts Individuais

```bash
# Download
python download.py

# Processamento
python clean_database.py

# Geração de ligas
python ligas.py
```

## 📊 Arquivos Gerados

### `database.csv`
- **Fonte**: Google Drive
- **Formato**: Dados brutos (uma linha por jogador por partida)
- **Tamanho**: ~70-75 MB
- **Uso**: Fonte de dados original

### `data_transformed.csv`
- **Fonte**: Processamento de `database.csv`
- **Formato**: Dados limpos (uma linha por partida/matchup)
- **Tamanho**: ~2-3 MB
- **Uso**: Dados prontos para análise de apostas
- **Colunas principais**:
  - `league`, `year`, `date`
  - `t1`, `t2` (times)
  - `result_t1` (0 = perdeu, 1 = ganhou)
  - `top_t1`, `jung_t1`, `mid_t1`, `adc_t1`, `sup_t1` (composição time 1)
  - `top_t2`, `jung_t2`, `mid_t2`, `adc_t2`, `sup_t2` (composição time 2)
  - `total_kills`, `total_barons`, `total_towers`, etc.

### `ligas_times.json`
- **Fonte**: Processamento de `data_transformed.csv`
- **Formato**: JSON com mapeamento liga → lista de times
- **Uso**: Referência para identificar diferenças de escrita entre sites de apostas
- **Exemplo**:
```json
{
  "LEC": ["Fnatic", "G2 Esports", "Karmine Corp", ...],
  "LCK": ["T1", "Gen.G", "Dplus KIA", ...]
}
```

## 🗄️ Banco de Dados SQLite (Opcional)

Para melhor performance em consultas, você pode migrar para SQLite:

```bash
# Inicializar banco
python database_schema.py init

# Importar CSV para banco
python database_schema.py import

# Ver estatísticas
python database_schema.py stats
```

### Estrutura do Banco

- **`matchups`**: Tabela principal com informações dos jogos
- **`compositions`**: Composições de champions por time
- **`leagues_teams`**: Cache de times por liga

### Consultas Úteis

```python
import sqlite3
import pandas as pd

conn = sqlite3.connect('lol_history.db')

# Matchups de uma liga
df = pd.read_sql_query("""
    SELECT * FROM matchups 
    WHERE league = 'LEC' AND year = 2025
    ORDER BY date DESC
""", conn)

# Estatísticas de um time
df = pd.read_sql_query("""
    SELECT 
        COUNT(*) as total_games,
        SUM(CASE WHEN t1 = 'G2 Esports' AND result_t1 = 1 THEN 1 
                 WHEN t2 = 'G2 Esports' AND result_t1 = 0 THEN 1 
                 ELSE 0 END) as wins
    FROM matchups
    WHERE t1 = 'G2 Esports' OR t2 = 'G2 Esports'
""", conn)
```

## ⚙️ Configuração

Todas as configurações estão centralizadas em `config.py`:

```python
# Google Drive
GOOGLE_DRIVE_FILE_ID = "1hnpbrUpBMS1TZI7IovfpKeZfWJH1Aptm"

# Arquivos
DATABASE_CSV = "database.csv"
TRANSFORMED_CSV = "data_transformed.csv"
LIGAS_JSON = "ligas_times.json"
SQLITE_DB = "lol_history.db"
```

## 🔍 Validação e Logging

- **Validação de dados**: Verifica estrutura do CSV antes de processar
- **Logging**: Registra todas as operações em `data_processing.log`
- **Hash MD5**: Verifica integridade dos arquivos baixados
- **Tratamento de erros**: Mensagens claras e recuperação de falhas

## 📈 Melhorias Implementadas

### vs. Versão Original

✅ **Configuração centralizada** (`config.py`)  
✅ **Validação de dados** antes de processar  
✅ **Tratamento robusto de erros**  
✅ **Logging estruturado**  
✅ **Pipeline automatizado** (`main.py`)  
✅ **Verificação de integridade** (hash MD5)  
✅ **Progress bars** e feedback visual  
✅ **Documentação completa**  
✅ **Suporte a SQLite** (opcional, melhor performance)  

## 🐛 Troubleshooting

### Erro: "Arquivo não encontrado"
- Verifique se executou `download.py` primeiro
- Use `python main.py` para pipeline completo

### Erro: "Colunas faltando"
- O CSV pode estar desatualizado
- Baixe novamente com `python download.py`

### Erro: "Timeout no download"
- Verifique conexão com internet
- O arquivo é grande (~70 MB), pode demorar

### Performance lenta
- Considere usar SQLite: `python database_schema.py import`
- Consultas SQL são 10-100x mais rápidas que CSV

## 📚 Exemplos de Uso

### Análise de Matchups

```python
import pandas as pd

# Carrega dados limpos
df = pd.read_csv('data_transformed.csv')

# Filtra por liga
lec_games = df[df['league'] == 'LEC']

# Análise de vitórias
win_rate = lec_games.groupby('t1')['result_t1'].mean()
```

### Identificar Diferenças de Nomes

```python
import json

# Carrega mapeamento
with open('ligas_times.json', 'r', encoding='utf-8') as f:
    ligas = json.load(f)

# Busca time em todas as ligas
team_name = "G2"
for liga, times in ligas.items():
    matches = [t for t in times if team_name.lower() in t.lower()]
    if matches:
        print(f"{liga}: {matches}")
```

## 🔗 Integração com Projeto Principal

Este sistema é independente do projeto `pinnacle` (odds da Pinnacle), mas pode ser integrado:

1. Use `data_transformed.csv` para análise histórica
2. Use `ligas_times.json` para normalizar nomes de times
3. Use SQLite para consultas rápidas em grandes volumes

## 📝 Notas

- O arquivo `database.csv` é atualizado periodicamente no Google Drive
- Execute o pipeline regularmente para manter dados atualizados
- `ligas_times.json` é útil para identificar variações de nomes entre sites
- SQLite é opcional mas recomendado para grandes volumes de dados

## 📄 Licença

Este código faz parte do projeto Pinnacle.

---

**Última atualização**: 2026-01-22
