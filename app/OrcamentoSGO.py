import duckdb
import requests
import sys
import time
import os
import pandas as pd
from util.api_token import api_budget, api_budget_months, headers

def show_startup_animation():
    # Desenho simples em ASCII
    logo = [
        "  #####   #####    ##### ",
        " #     # #     #  #     #",
        " #       #        #     #",
        "  #####  #  ####  #     #",
        "       # #     #  #     #",
        " #     # #     #  #     #",
        "  #####   #####    ##### "
    ]

    # Animação do desenho
    for line in logo:
        print(line)
        time.sleep(0.1)  # Pequeno delay para criar o efeito de "desenho"

    # Mensagem de inicialização
    print("\n\nIniciando conexão com API SGO")
    
    # Animação de carregamento
    loading_animation = ["[=     ]", "[==    ]", "[===   ]", "[====  ]", "[===== ]", "[======]"]
    for i in range(3):  # Repetir a animação algumas vezes
        for frame in loading_animation:
            sys.stdout.write("\r" + frame)
            sys.stdout.flush()
            time.sleep(0.2)  # Delay entre os frames
    print("\n\nConexão estabelecida com sucesso!")

# Chamar a função para exibir a animação
show_startup_animation()

# Comando para obter o caminho padrão da area de trabalho em qualquer maquina
desktop_path = os.path.join(os.path.expanduser('~'), 'Desktop')

# Definindo o caminho para salvar os arquivos
nome_arquivo1 = 'Validacao dos Dados SGO.xlsx'
nome_arquivo2 = 'Controladoria.xlsx'
file_path_geral = os.path.join(desktop_path, nome_arquivo1)
file_path_grupo = os.path.join(desktop_path, nome_arquivo2)

# Requisições para obter os dados de budget na API /budgets/get-all
# E as tratativas caso algum erro ocorra na requsição 
try:
    response = requests.get(api_budget, headers=headers)
    response.raise_for_status()  # Lança uma exceção se a resposta não for 2xx
    # Caso o status seja 200, processa o JSON normalmente
    budget = response.json()

except requests.exceptions.HTTPError as http_err:
    # Trata erros HTTP específicos com base no código de status
    if response.status_code == 401:
        print("Erro de autenticação. Verifique o token de acesso.")
    elif response.status_code == 404:
        print("Recurso não encontrado. Verifique a URL da API.")
    elif response.status_code == 500:
        print("Erro interno do servidor. Tente novamente mais tarde.")
    else:
        print(f"Erro HTTP ao acessar a API: {response.status_code} - {http_err}")
    sys.exit(1)  # Encerra o programa com código de erro

except requests.exceptions.RequestException as req_err:
    # Trata erros de conexão, tempo de espera, etc.
    print(f"Erro ao tentar se conectar à API: {req_err}")
    sys.exit(1)  # Encerra o programa com código de erro

except Exception as err:
    # Trata qualquer outro erro inesperado
    print(f"Ocorreu um erro inesperado: {err}")
    sys.exit(1)  # Encerra o programa com código de erro

# Criando um banco de dados temporário no DuckDB
con = duckdb.connect(database=':memory:')

# Convertendo os dados JSON para DataFrames do Pandas
budget_df = pd.json_normalize(budget, sep='_', meta=[
    'active', 'id', 'contractNumber', 'adjustmentMonth', 'adjustmentPercentage',
    'value', 'cycleId', 'budgetAccountId', 'supplierId', 'originId',
    'levelSixId', 'managerId', 'apportionmentId'
], record_prefix='', errors='ignore')

# Criando um DataFrame para armazenar os detalhes dos meses
budget_months_list = []

# Definindo o número máximo de tentativas para o caso de 429
max_retries = 3

# Fazendo uma requisição para cada orçamento para obter os detalhes dos meses
for budget_entry in budget:
    budget_id = budget_entry['id']
    retries = 0  # Contador de tentativas

    while retries < max_retries:
        # Requisições para obter os dados de budget POR ID na API /budget-months/get-by-budget-id?budgetId=X
        response_months = requests.get(f"{api_budget_months}?budgetId={budget_id}", headers=headers)

        if response_months.status_code == 200:
            budget_months = response_months.json()
            for item in budget_months:
                # Adicionando os dados ao budget_months_list
                budget_months_list.append(item)
            print(f"Itens do Orcamento do id: {budget_id}, obtidos com sucesso.")
            # Pequeno atraso após uma requisição bem-sucedida
            time.sleep(1)
            break  # Sai do loop, pois a requisição foi bem-sucedida

        elif response_months.status_code == 429:
            # Tratamento para quando a API retornar "Too Many Requests"
            retries += 1
            print(f"Tempo limite da API excedido para o budgetId {budget_id}. Tentativa {retries} de {max_retries}. Aguardando antes de tentar novamente.")
            time.sleep(2 * retries)  # Aumenta o tempo de espera exponencialmente

        else:
            print(f"Erro ao obter os detalhes do orçamento para o budgetId {budget_id}: {response_months.status_code}")
            # Se ocorrer qualquer outro erro, encerra o programa
            sys.exit(1)
    else:
        # Se o número máximo de tentativas for atingido sem sucesso, encerra o programa
        print(f"Falha ao obter os dados para o budget {budget_id} após {max_retries} tentativas.")

print('\n\nDados obtidos, construindo arquivos...')

# Convertendo os dados de budget_months para um DataFrame
budget_months_df = pd.json_normalize(budget_months_list, sep='_', errors='ignore')

# Carregando os DataFrames para tabelas no DuckDB
con.register('budget', budget_df)
con.register('budget_months', budget_months_df)

# Unindo os dados de budget e budget months
df_geral = con.execute('''
    SELECT 
        b.id AS Id_Orçamento,
        b.contractNumber AS Contrato,
        b.adjustmentMonth AS Mes_Reajuste,
        b.adjustmentPercentage AS Reajuste_Percentual,
        b.value AS Valor,
        b.supplier_code AS Cod_Fornecedor,
        b.budgetAccount_description AS Conta_Contabil,
        b.supplier_description AS Fornecedor,
        b.origin_description AS Origem,
        bm.budgetApportionmentItem_sector_code AS COD_SETOR,
        bm.budgetApportionmentItem_sector_codeCostCenter AS COD_CCUSTO,
        bm.budgetApportionmentItem_sector_name AS CENTRO_CUSTO,
        bm.budgetApportionmentItem_base AS BASE,
        bm.budgetApportionmentItem_sector_company_name AS EMPRESA,
        b.levelSix_description AS Nivel,
        b.manager_description AS Gestor,
        b.apportionment_name AS Criterio,
        b.apportionment_description AS Descricao_criterio,
        b.cycle_budgetYear AS Ano,
        bm.january AS Janeiro,
        bm.february AS Fevereiro,
        bm.march AS Março,
        bm.april AS Abril,
        bm.may AS Maio,
        bm.june AS Junho,
        bm.july AS Julho,
        bm.august AS Agosto,
        bm.september AS Setembro,
        bm.october AS Outubro,
        bm.november AS Novembro,
        bm.december AS Dezembro,
        -- Soma total anual
        COALESCE(bm.january, 0) + COALESCE(bm.february, 0) + COALESCE(bm.march, 0) +
        COALESCE(bm.april, 0) + COALESCE(bm.may, 0) + COALESCE(bm.june, 0) +
        COALESCE(bm.july, 0) + COALESCE(bm.august, 0) + COALESCE(bm.september, 0) +
        COALESCE(bm.october, 0) + COALESCE(bm.november, 0) + COALESCE(bm.december, 0) AS Total_Anual
    FROM budget b
    JOIN budget_months bm ON b.id = bm.budgetId
''').fetchdf()

df_grupo = con.execute('''
    SELECT
        b.cycle_budgetYear AS ANO,
        b.budgetAccount_code AS COD_CODCONTA,
        b.budgetAccount_description AS CONTA_N05,
        b.supplier_code AS COD_FORNECEDOR,
        b.supplier_description AS DES_FORNECEDOR,
        b.levelSix_description AS "NIVEL 6",   
        b.origin_description AS ORIGEM, 
        b.contractNumber AS "Nº CONTRATO",
        b.manager_description AS GESTOR,
        bm.budgetApportionmentItem_sector_code AS COD_SETOR,
        bm.budgetApportionmentItem_sector_codeCostCenter AS COD_CCUSTO,
        bm.budgetApportionmentItem_sector_name AS CENTRO_CUSTO,
        bm.budgetApportionmentItem_base AS BASE,
        b.adjustmentPercentage AS "%",
        COALESCE(bm.january, 0) AS JANEIRO,
        COALESCE(bm.february, 0) AS FEVEREIRO,
        COALESCE(bm.march, 0) AS MARÇO,
        COALESCE(bm.april, 0) AS ABRIL,
        COALESCE(bm.may, 0) AS MAIO,
        COALESCE(bm.june, 0) AS JUNHO,
        COALESCE(bm.july, 0) AS JULHO,
        COALESCE(bm.august, 0) AS AGOSTO,
        COALESCE(bm.september, 0) AS SETEMBRO,
        COALESCE(bm.october, 0) AS OUTUBRO,
        COALESCE(bm.november, 0) AS NOVEMBRO,
        COALESCE(bm.december, 0) AS DEZEMBRO,
        -- Soma total anual
        COALESCE(bm.january, 0) + COALESCE(bm.february, 0) + COALESCE(bm.march, 0) +
        COALESCE(bm.april, 0) + COALESCE(bm.may, 0) + COALESCE(bm.june, 0) +
        COALESCE(bm.july, 0) + COALESCE(bm.august, 0) + COALESCE(bm.september, 0) +
        COALESCE(bm.october, 0) + COALESCE(bm.november, 0) + COALESCE(bm.december, 0) AS TOTAL
    FROM budget b
    JOIN budget_months bm ON b.id = bm.budgetId
''').fetchdf()

# Salvando os resultados em arquivos Excel
df_geral.to_excel(file_path_geral, index=False)
if os.path.exists(file_path_geral):
    print(f"\n\nArquivo {file_path_geral}, gerado com sucesso na sua Área de Trabalho.")
    time.sleep(5)
else:
    print(f"\nFalha ao gerar o arquivo {file_path_geral}.")


df_grupo.to_excel(file_path_grupo, index=False)
if os.path.exists(file_path_grupo):
    print(f"\n\nArquivo {file_path_grupo}, gerado com sucesso na sua Área de Trabalho.")
    time.sleep(5)
else:
    print(f"\nFalha ao gerar o arquivo {file_path_grupo}.")

print('\n\n\nObrigado pela paciencia.')

# Fechando a conexão com o banco de dados DuckDB
con.close()

time.sleep(10)